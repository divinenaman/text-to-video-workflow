from typing import List, Optional, TYPE_CHECKING, Any
import os

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import ForeignKey, Index, create_engine, event
from sqlalchemy.orm import relationship, Mapped, mapped_column, sessionmaker
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm.attributes import get_history
from datetime import datetime

is_testing = False
try:
    # for sqlite during tests
    is_testing = os.environ["TESTING"] == "True"
except Exception:
    pass

if is_testing:
    from sqlalchemy.dialects.sqlite import JSON as JSONB
else:
    from sqlalchemy.dialects.postgresql import JSONB

db = SQLAlchemy()


_engine = None
_Session = None


def create_new_db_session(db_uri):
    global _engine, _Session

    # Initialize only if it hasn't been done yet for this process
    if _engine is None:
        _engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                "keepalives": 1,
                "keepalives_idle": 60,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            },
        )
        _Session = sessionmaker(bind=_engine)

    # Return a new session from the existing session factory
    return _Session()


# Only for type checking, not for runtime
if TYPE_CHECKING:
    from flask_sqlalchemy.model import DefaultMeta

    class Model(metaclass=DefaultMeta):
        query: Any

else:
    Model = db.Model


# SQLAlchemy model representing 'ideas', with 'id' as a primary key storing a unique 36-character
# identifier for each idea, 'prompt' for a text description up to 1000 characters, and 'length' possibly for
# a numeric value related to idea length; the constructor initializes instances with 'idea_id', 'prompt', and 'length'.
class Idea(Model):
    __tablename__ = "ideas"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(db.String(36))
    prompt: Mapped[str] = mapped_column(db.String(1000))
    length: Mapped[int] = mapped_column(db.Integer)
    is_series: Mapped[bool] = mapped_column(db.Boolean, default=False)
    episode_breakdown: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (Index("idx_ideas_user_id", "user_id"),)

    def __init__(
        self,
        idea_id,
        user_id,
        prompt,
        length,
        is_series: bool = False,
        episode_breakdown: Optional[Any] = None,
    ):
        self.id = idea_id
        self.user_id = user_id
        self.prompt = prompt
        self.length = length
        self.is_series = is_series
        self.episode_breakdown = episode_breakdown


# SQLAlchemy model representing 'voices' in the database, with 'id' as the primary key, 'voice_name' as a unique string
# for voice identification, 'voice_sample' for URL of voice data, 'tags' as an array of strings for categorization,
# and 'description' for voice details; includes a back reference to access related drafts via the 'drafts'
# relationship; constructor initializes instances with 'voice_name', 'voice_sample', optional 'tags', and 'description'.
class Voice(Model):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(db.String, primary_key=True)
    voice_name: Mapped[str] = mapped_column(db.String, unique=True, nullable=False)
    voice_sample: Mapped[str] = mapped_column(db.String, nullable=False)
    tags = mapped_column(JSONB)
    description: Mapped[str] = mapped_column(db.String)
    tts_toolkit: Mapped[str] = mapped_column(db.String, nullable=False)

    # Define a back reference to access drafts associated with a voice
    drafts = relationship("Draft", back_populates="voice")

    def __init__(
        self,
        voice_id,
        voice_name,
        voice_sample,
        tts_toolkit,
        tags=None,
        description=None,
    ):
        self.id = voice_id
        self.voice_name = voice_name
        self.voice_sample = voice_sample
        self.tags = tags
        self.description = description
        self.tts_toolkit = tts_toolkit


# SQLAlchemy model representing 'background_music' in the database, featuring 'id' as the primary key, 'music_name'
# as a unique string for music identification, 'music_sample' for URL of music data,
# 'tags' as an array of strings for categorization, and 'description' for music details; includes a back reference to
# access related drafts via the 'drafts' relationship; constructor initializes instances with
# 'music_name', 'music_sample', optional 'tags', and 'description'.
class BackgroundMusic(Model):
    __tablename__ = "background_music"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    music_name: Mapped[str] = mapped_column(db.String, unique=True, nullable=False)
    music_sample: Mapped[str] = mapped_column(
        db.String, nullable=False
    )  # You can change the data type as needed
    tags = mapped_column(JSONB)
    description: Mapped[str] = mapped_column(db.String)
    transition: Mapped[bool] = mapped_column(db.Boolean, nullable=False)
    embedding: Mapped[Vector] = mapped_column(Vector(384), nullable=True)

    # Define a back reference to access drafts associated with background music
    drafts = relationship("Draft", back_populates="background_music")

    def __init__(
        self,
        music_name,
        music_sample,
        transition,
        tags=None,
        description=None,
        embedding=None,
        row_id=None,
    ):
        self.id = row_id or self.id
        self.music_name = music_name
        self.music_sample = music_sample
        self.tags = tags
        self.description = description
        self.transition = transition
        self.embedding = embedding


# SQLAlchemy model representing 'styles' in the database, featuring 'id' as the primary key, 'style_name'
# as a unique string for style identification, 'style_sample' for URL of style data,
# 'tags' as an array of strings for categorization, and 'description' for style details; includes a back reference to
# access related drafts via the 'drafts' relationship; constructor initializes instances with
# 'style_name', 'style_sample', optional 'tags', and 'description'.
class Styles(Model):
    __tablename__ = "styles"

    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    style_name: Mapped[str] = mapped_column(db.String, unique=True, nullable=False)
    style_sample: Mapped[str] = mapped_column(
        db.String, nullable=False
    )  # You can change the data type as needed
    tags = mapped_column(JSONB)
    description: Mapped[str] = mapped_column(db.String)

    # Define a back reference to access drafts associated with style
    drafts = relationship("Draft", back_populates="style")

    def __init__(
        self, style_name, style_sample, tags=None, description=None, row_id=None
    ):
        self.id = row_id or self.id
        self.style_name = style_name
        self.style_sample = style_sample
        self.tags = tags
        self.description = description


class MkDraftStages:
    def __init__(self) -> None:
        self.STORY_GEN = 0
        self.CHARACTER_REF_GEN = 1
        self.IMAGE_PROMPT_GEN = 2
        self.IMAGE_GEN = 3
        self.IMAGE_UPSCALE = 4
        self.AUDIO_GEN_VIDEO_CONFIG_GEN = 5
        self.VIDEO_GEN_STARTED = 6
        self.VIDEO_GEN_PROCESSING = 7
        self.VIDEO_GEN_FAILED = 8
        self.VIDEO_GENERATED = 9
        self.DRAFT_FAILED = 100


class MkAssetGenStages:
    def __init__(self) -> None:
        self.TEXT = 0
        self.AUDIO = 1
        self.IMAGE = 2
        self.AVATAR = 3
        self.BGM = 4
        self.SOUNDS = 5
        self.SEARCH = 6


DraftStages = MkDraftStages()
AssetGenStages = MkAssetGenStages()


class Draft(Model):
    __tablename__ = "drafts"

    idea_id: Mapped[str] = mapped_column(
        db.String(36), ForeignKey("ideas.id"), nullable=False, primary_key=True
    )
    version: Mapped[int] = mapped_column(db.Integer, nullable=False, primary_key=True)
    story: Mapped[str] = mapped_column(db.Text, nullable=False)
    title: Mapped[str] = mapped_column(db.Text, nullable=False)

    image_descriptions: Mapped[List[str]] = mapped_column(
        JSONB if is_testing else db.ARRAY(db.String(2000))
    )
    processed: Mapped[bool] = mapped_column(db.Boolean(), unique=False, default=False)
    # Define the foreign key relationships with other tables
    voice_id: Mapped[Optional[str]] = mapped_column(
        db.String(36), ForeignKey("voices.id")
    )
    background_music_id: Mapped[Optional[int]] = mapped_column(
        db.Integer, ForeignKey("background_music.id")
    )
    style_id: Mapped[Optional[int]] = mapped_column(db.Integer, ForeignKey("styles.id"))
    # Define a back reference to access drafts associated with an idea
    voice = relationship("Voice", back_populates="drafts")
    background_music = relationship("BackgroundMusic", back_populates="drafts")
    style = relationship("Styles", back_populates="drafts")
    video_data: Mapped[Optional[str]] = mapped_column(db.Text)
    remotion_config: Mapped[Optional[str]] = mapped_column(db.Text)
    generated_video: Mapped[Optional[str]] = mapped_column(db.Text)
    character_ref: Mapped[Optional[str]] = mapped_column(db.Text)
    stage: Mapped[int] = mapped_column(db.Integer, default=-1)
    target_stage: Mapped[int] = mapped_column(db.Integer, default=-1)
    episode_index: Mapped[Optional[int]] = mapped_column(
        db.Integer, nullable=True, default=None
    )
    style_reference_urls: Mapped[Optional[List[str]]] = mapped_column(
        JSONB if is_testing else db.ARRAY(db.String(2000))
    )

    stage_updated_at = mapped_column(db.DateTime, default=datetime.utcnow)

    created_at = mapped_column(db.DateTime, default=datetime.utcnow)

    def __init__(
        self,
        idea_id,
        version,
        story,
        title,
        image_descriptions: Optional[List[str]] = None,
        voice_id: Optional[str] = None,
        background_music_id: Optional[int] = None,
        style_id: Optional[int] = None,
        stage: int = -1,
        episode_index: Optional[int] = None,
        style_reference_urls: Optional[List[str]] = None,
    ):

        self.idea_id = idea_id
        self.version = version
        self.story = story
        self.title = title
        self.image_descriptions = image_descriptions or []
        self.voice_id = voice_id
        self.background_music_id = background_music_id
        self.style_id = style_id
        self.processed = False
        self.video_data = None
        self.remotion_config = None
        self.generated_video = None
        self.character_ref = None
        self.stage = stage
        self.episode_index = episode_index
        self.style_reference_urls = style_reference_urls or []


# Create the event listener function
@event.listens_for(Draft, "before_update")
def receive_before_update(mapper, connection, target):

    # get_history() returns a tuple of (added, unchanged, deleted) values
    history = get_history(target, "stage")

    if history.added:
        target.stage_updated_at = datetime.utcnow()
