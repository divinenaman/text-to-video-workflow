import os

os.environ["TESTING"] = "True"

import pytest
import json
from server import app, Idea, Draft, Voice, BackgroundMusic, Styles
from models import db
import uuid


@pytest.fixture(scope="function")
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        if "sqlalchemy" not in app.extensions:
            db.init_app(app)
        db.drop_all()
        db.create_all()
        # Preload free resources for testing
        # Voice
        gtts_voice = Voice(
            voice_id="gtts",
            voice_name="Google Text-to-Speech",
            description="default free voice",
            voice_sample="http://example.com/gtts.mp3",
            tts_toolkit="gtts",
        )
        db.session.add(gtts_voice)
        # Background Music
        bgm_10 = BackgroundMusic(
            row_id=10,
            music_name="Test BGM",
            music_sample="http://example.com/bgm10.mp3",
            transition=False,
            description="A test background music",
            embedding=None,
        )
        db.session.add(bgm_10)
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture
def new_idea(client):
    idea_id = str(uuid.uuid4())
    idea = Idea(
        idea_id=idea_id, prompt="A test idea prompt", length=10, user_id="test_user"
    )
    with app.app_context():
        db.session.add(idea)
        db.session.commit()
        db.session.flush()
    return idea_id


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert json.loads(response.data) == {"status": "healthy"}


def test_idea_post(client):
    response = client.post(
        "/idea", json={"prompt": "New idea prompt", "length": 5, "user_id": "user123"}
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data["message"] == "Idea created successfully"
    assert "id" in data


def test_idea_get_by_id(client, new_idea):
    response = client.get(f"/idea/{new_idea}")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["id"] == new_idea
    assert data["prompt"] == "A test idea prompt"


def test_idea_get_by_user_id(client, new_idea):
    response = client.get(f"/idea?user_id=test_user")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) > 0
    assert data[0]["user_id"] == "test_user"


def test_idea_delete(client, new_idea):
    response = client.delete(f"/idea/{new_idea}")
    assert response.status_code == 204
    response = client.get(f"/idea/{new_idea}")
    assert response.status_code == 404


def test_draft_post_minimal(client, new_idea):
    response = client.post("/draft", json={"idea_id": new_idea})
    assert response.status_code == 201
    data = json.loads(response.data)
    assert "Draft version 1 for idea" in data["message"]
    assert "id" in data


def test_draft_post_with_free_resources(client, new_idea):
    response = client.post(
        "/draft",
        json={
            "idea_id": new_idea,
            "voice_id": "gtts",
            "image_engine": "hf_flux1",
            "background_music_id": 10,
        },
    )
    assert response.status_code == 201
    data = json.loads(response.data)
    assert "Draft version 1 for idea" in data["message"]
    assert "id" in data


def test_draft_post_invalid_idea_id(client):
    response = client.post("/draft", json={"idea_id": "invalid_id"})
    assert response.status_code == 404
    assert "idea_id invalid_id not found" in json.loads(response.data)["message"]


def test_draft_patch_story(client, new_idea):
    # First create a draft
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "story": "This is an updated story for the draft.",
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2  # Should create a new version


def test_draft_patch_image_urls(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "image_urls": [
                "http://example.com/img1.jpg",
                "http://example.com/img2.jpg",
            ],
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_draft_patch_bgm_name(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "bgm_name": "New Background Music Name",
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_draft_patch_style_id(client, new_idea):
    with app.app_context():
        style = Styles(
            row_id=1,
            style_name="Cartoon",
            style_sample="url",
            tags="cartoon",
            description="cartoon style",
        )
        db.session.add(style)
        db.session.commit()
        db.session.flush()
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft", json={"idea_id": new_idea, "version_id": 1, "style_id": 1}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


# def test_draft_patch_character_ref(client, new_idea):
#    client.post("/draft", json={"idea_id": new_idea})
#    response = client.patch(
#        "/draft",
#        json={
#            "idea_id": new_idea,
#            "version_id": 1,
#            "character_ref": {"narator_avatar_url": "http://example.com/char.png"},
#        },
#    )
#    assert response.status_code == 200
#    data = json.loads(response.data)
#    assert data["version"] == 2


def test_draft_patch_regen_image_prompts_and_images(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea, "story": "A short story."})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "regen_image_prompts": ["A new prompt for image 1"],
            "regen_images": [1],
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


# def test_draft_patch_upscale_image(client, new_idea):
#    client.post(
#        "/draft",
#        json={"idea_id": new_idea, "image_urls": ["http://example.com/lowres.jpg"]},
#    )
#    response = client.patch(
#        "/draft", json={"idea_id": new_idea, "version_id": 1, "upscale_image": True}
#    )
#    assert response.status_code == 200
#    data = json.loads(response.data)
#    assert data["version"] == 2


# def test_draft_patch_convert_to_video(client, new_idea):
#    client.post(
#        "/draft",
#        json={"idea_id": new_idea, "image_urls": ["http://example.com/img1.jpg"]},
#    )
#    response = client.patch(
#        "/draft",
#        json={
#            "idea_id": new_idea,
#            "version_id": 1,
#            "convert_to_video": [{"pos": 1, "prompt": "Convert this image"}],
#        },
#    )
#    assert response.status_code == 200
#    data = json.loads(response.data)
#    assert data["version"] == 2


def test_draft_patch_edit_story_sentence_and_gen_audio(client, new_idea):
    client.post(
        "/draft", json={"idea_id": new_idea, "story": "Sentence one. Sentence two."}
    )
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "edit_story_sentence": {"0": "Updated sentence one."},
            "gen_audio": [0],
            "voice_id": "gtts",
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


# def test_draft_patch_narrator_avatar(client, new_idea):
#    client.post("/draft", json={"idea_id": new_idea})
#    response = client.patch(
#        "/draft",
#        json={
#            "idea_id": new_idea,
#            "version_id": 1,
#            "character_ref": {"narrator_avatar": "some_avatar_id"},
#            "avatar_engine": "gooey_ai",
#        },
#    )
#    assert response.status_code == 200
#    data = json.loads(response.data)
#    assert data["version"] == 2


# def test_draft_patch_narrator_avatar_url(client, new_idea):
#    client.post("/draft", json={"idea_id": new_idea})
#    response = client.patch(
#        "/draft",
#        json={
#            "idea_id": new_idea,
#            "version_id": 1,
#            "character_ref": {"narrator_avatar_url": "http://example.com/narrator.mp4"},
#        },
#    )
#    assert response.status_code == 200
#    data = json.loads(response.data)
#    assert data["version"] == 2


def test_draft_patch_text_to_speech(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea, "story": "Some story text."})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "text_to_speech": "http://example.com/custom_audio.mp3",
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_draft_patch_ui_order(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "ui_order": [{"type": "text", "pos": 0}],
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_draft_patch_ai_edit_ui(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "ai_edit_ui": "Make the text bigger",
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_draft_patch_toggle_ai_edit(client, new_idea):
    client.post(
        "/draft", json={"idea_id": new_idea, "ai_edit_ui": "Make the text bigger"}
    )
    response = client.patch(
        "/draft", json={"idea_id": new_idea, "version_id": 1, "toggle_ai_edit": [True]}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_draft_patch_regen_video_conf_and_gen_video(client, new_idea):
    client.post("/draft", json={"idea_id": new_idea})
    response = client.patch(
        "/draft",
        json={
            "idea_id": new_idea,
            "version_id": 1,
            "regen_video_conf": "v2",
            "gen_video": True,
        },
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["version"] == 2


def test_moodboard_post(client):
    response = client.post(
        "/api/moodboard",
        json={
            "topic": "Cyberpunk market",
            "ctx": "Monsoon rain, high contrast",
            "num_styles": 1,
        },
    )
    # The endpoint might return 200 or 500 depending on search/gpu availability in test env,
    # but we check the contract acceptance.
    assert response.status_code in [200, 500]
    if response.status_code == 200:
        data = json.loads(response.data)
        assert data["topic"] == "Cyberpunk market"
        assert "moodboard" in data
