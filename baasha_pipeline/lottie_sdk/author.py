"""Sandboxed execution of LLM-authored SDK code + mechanical gates (G0/G1).

No LLM calls here — pure execution and render checks. The vision judge (G2)
lives in ``lottie_assets.py``.
"""

from __future__ import annotations

import io
from typing import Any, Callable, Dict, List, Optional, Tuple

from .model import (
    CharacterRig,
    CharacterInstance,
    Scene,
    Part,
    Pose,
    Clip,
    Shape,
    ShapeKind,
    Prop,
    slugify,
)
from .compiler import compile_instance, compile_rig, compile_scene
from .validate import LottieValidationError, validate_lottie, validate_rig, validate_scene
from .render import LottieBrowserManager, frame_is_nonblank, render_keyframes
from ..logger import logging

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    allowed_prefixes = ("baasha_pipeline.lottie_sdk", "baasha_pipeline.lottie_sdk.model")
    if level != 0:
        raise ImportError("relative imports are not allowed")
    if name != "baasha_pipeline.lottie_sdk" and not name.startswith(allowed_prefixes):
        raise ImportError(f"import of {name!r} is not allowed in lottie authoring")
    import importlib

    return importlib.import_module(name)


_ALLOWED_BUILTINS = {
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sorted": sorted,
    "reversed": reversed,
    "isinstance": isinstance,
    "True": True,
    "False": False,
    "None": None,
    "__build_class__": __build_class__,
    "__name__": "lottie_author",
    "__import__": _safe_import,
}

_SDK_EXPORTS = {
    "CharacterRig": CharacterRig,
    "CharacterInstance": CharacterInstance,
    "Scene": Scene,
    "Part": Part,
    "Pose": Pose,
    "Clip": Clip,
    "Shape": Shape,
    "ShapeKind": ShapeKind,
    "Prop": Prop,
    "slugify": slugify,
}


class AuthorExecError(Exception):
    def __init__(self, message: str, line: Optional[int] = None):
        self.line = line
        super().__init__(message)


def _extract_python_block(text: str) -> str:
    if "```" not in text:
        return text.strip()
    parts = text.split("```")
    for i in range(1, len(parts), 2):
        block = parts[i]
        if block.startswith("python"):
            return block[len("python") :].strip()
        if block.startswith("py"):
            return block[len("py") :].strip()
        if "\n" in block and not block.split("\n", 1)[0].strip().isalpha():
            return block.strip()
    return parts[1].split("\n", 1)[-1].strip() if len(parts) > 1 else text.strip()


def _exec_error_message(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}"
    if isinstance(e, TypeError) and "positional" in str(e):
        msg += (
            " - SDK constructors are keyword-only: write"
            ' Part(name="torso", ...) / CharacterRig(name="hero", ...),'
            " never Part(\"torso\", ...)"
        )
    return msg


def exec_rig_source(source: str) -> CharacterRig:
    """Execute LLM-authored Python in a restricted namespace; return the rig.

    Convention: code defines ``rig = CharacterRig(...)`` or
    ``def build_rig() -> CharacterRig``.
    """
    code = _extract_python_block(source)
    namespace: Dict[str, Any] = {"__builtins__": _ALLOWED_BUILTINS, **_SDK_EXPORTS}
    try:
        exec(compile(code, "<lottie-rig>", "exec"), namespace)  # noqa: S102
    except SyntaxError as e:
        raise AuthorExecError(f"SyntaxError: {e.msg}", line=e.lineno) from e
    except LottieValidationError as e:
        raise AuthorExecError(f"model validation: {e}") from e
    except Exception as e:
        raise AuthorExecError(_exec_error_message(e)) from e

    obj = namespace.get("rig")
    if obj is None and callable(namespace.get("build_rig")):
        try:
            obj = namespace["build_rig"]()
        except LottieValidationError as e:
            raise AuthorExecError(f"build_rig validation: {e}") from e
        except Exception as e:
            raise AuthorExecError(f"build_rig raised {_exec_error_message(e)}") from e
    if not isinstance(obj, CharacterRig):
        # Accept a rig bound to any other name (character/hero/<char_name>).
        found = [
            v
            for k, v in namespace.items()
            if not k.startswith("__") and isinstance(v, CharacterRig)
        ]
        if not found:
            for k, v in list(namespace.items()):
                if k in _SDK_EXPORTS or k.startswith("__") or not callable(v):
                    continue
                if any(t in k.lower() for t in ("rig", "character", "build", "make")):
                    try:
                        r = v()
                    except Exception:
                        continue
                    if isinstance(r, CharacterRig):
                        found.append(r)
                        break
        if len(found) == 1:
            obj = found[0]
    if not isinstance(obj, CharacterRig):
        raise AuthorExecError("source must define `rig = CharacterRig(...)` or `def build_rig()`")
    return obj


def exec_scene_source(source: str, character_rigs: Dict[str, CharacterRig]) -> Scene:
    """Execute LLM-authored scene code with prebuilt character rigs in scope.

    Convention: code defines ``scene = Scene(...)`` or ``def build_scene()``.
    Characters are available as ``CHARACTERS`` dict and as ``__all_rigs`` list.
    """
    code = _extract_python_block(source)
    namespace: Dict[str, Any] = {
        "__builtins__": _ALLOWED_BUILTINS,
        **_SDK_EXPORTS,
        "CHARACTERS": character_rigs,
        "__all_rigs": list(character_rigs.values()),
    }
    try:
        exec(compile(code, "<lottie-scene>", "exec"), namespace)  # noqa: S102
    except SyntaxError as e:
        raise AuthorExecError(f"SyntaxError: {e.msg}", line=e.lineno) from e
    except LottieValidationError as e:
        raise AuthorExecError(f"model validation: {e}") from e
    except Exception as e:
        raise AuthorExecError(_exec_error_message(e)) from e

    obj = namespace.get("scene")
    if obj is None and callable(namespace.get("build_scene")):
        try:
            obj = namespace["build_scene"]()
        except LottieValidationError as e:
            raise AuthorExecError(f"build_scene validation: {e}") from e
        except Exception as e:
            raise AuthorExecError(f"build_scene raised {_exec_error_message(e)}") from e
    if not isinstance(obj, Scene):
        raise AuthorExecError("source must define `scene = Scene(...)` or `def build_scene()`")
    return obj


def gate_rig_g0(rig: CharacterRig) -> dict:
    """G0: model + compile + structural validation. Returns compiled doc."""
    validate_rig(rig)
    clips = [c.name for c in rig.clips] or [None]
    poses = [p.name for p in rig.poses] or [None]
    doc = compile_rig(rig, clip=clips[0], pose=None if clips[0] else poses[0])
    errors = validate_lottie(doc)
    if errors:
        raise LottieValidationError(errors)
    return doc


def gate_rig_g1(
    doc: dict,
    browser: Optional[LottieBrowserManager] = None,
    n_frames: int = 3,
    ink_threshold: float = 0.004,
) -> Tuple[bool, List[Tuple[int, bytes]], List[str]]:
    """G1: render keyframes; every frame must be non-blank."""
    owns = browser is None
    bm = browser or LottieBrowserManager()
    problems: List[str] = []
    try:
        if owns:
            bm.start()
        frames = render_keyframes(doc, n=n_frames, browser=bm)
        for f, png in frames:
            if not frame_is_nonblank(png, ink_threshold=ink_threshold):
                problems.append(f"frame {f} is blank/near-blank")
        return (not problems, frames, problems)
    finally:
        if owns:
            bm.stop()


def turnaround_frames(doc: dict, clip_frames: Optional[List[int]] = None) -> List[int]:
    """Frames to render for a character turnaround sheet."""
    op = int(doc.get("op", 1))
    if clip_frames:
        return [f for f in clip_frames if 0 <= f < op]
    if op <= 1:
        return [0]
    return [0, op // 2, max(op - 1, 0)]


def gate_scene_g0(scene: Scene) -> dict:
    validate_scene(scene)
    doc = compile_scene(scene)
    errors = validate_lottie(doc)
    if errors:
        raise LottieValidationError(errors)
    return doc
