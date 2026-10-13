import re
from . import joins
from .. import errors


@errors.raise_ctx_errors
def basic_newline_splitter(data):
    def temp(text):
        skip = data.get("skip", 1)

        if text == "":
            return []
        text = text.strip()
        splits = text.splitlines()
        return splits[skip:]

    return temp


@errors.raise_ctx_errors
def markdown_parse(a, lang="json"):
    try:
        s = a.find(f"```{lang}")
        is_json = lang == "json"
        if s != -1:
            s = s + len(lang) + 3

            if is_json:
                while a[s] not in ["{", "["] and s < len(a):
                    s += 1

            e = a.find("```", s + 1)

            if is_json:
                while a[e - 1] not in ["}", "]"] and e - 1 > s:
                    e -= 1

            if e != -1:
                return a[s:e]

        return None
    except:
        return None


# wip
@errors.raise_ctx_errors
def json_splitter(data):
    def temp(text):
        keys = data.get("json_keys", [])

        if len(keys) < 1:
            return []

        if not text:
            return []

        # split by closing brace, breaks for nested json
        splits = text.split("}")

        regex = '"(?P<key>.+?)".*?:.*?"(?P<value>.+?)"'
        result = []

        # patch unwanted quotes before curly-brace (start of json)
        def patch_str(s):
            curl = s.find("{")
            dquote = s.find('"')
            if curl == -1:
                return s

            if curl > dquote:
                return s[curl:]
            else:
                return s

        # patch unwanted character escape (\)
        def patch_key(k):
            return k.strip().replace("\\", "")

        for s in splits:
            if s == "":
                continue

            s = patch_str(s)

            # DOTALL extends `.` to match newlines
            matched = re.finditer(regex, s, re.DOTALL)
            res = {}
            for k in keys:
                res[k] = ""

            for m in matched:
                d = m.groupdict()
                print(d)

                key = patch_key(d.get("key"))
                val = patch_key(d.get("value"))

                if not key or not val:
                    continue
                key = key.strip()
                if key in keys:
                    res[key] = val
            if res:
                # dict to string
                # keys are assumed ordered
                if not (data.get("join", True)):
                    result.append(res)
                else:
                    joined_str = joins.join_dict(res, keys)
                    if joined_str == "":
                        continue
                    result.append(joined_str)

        return result

    return temp
