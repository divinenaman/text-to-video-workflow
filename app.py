from server import app, load_prod_env, VoiceResource
import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import configparser

config = configparser.ConfigParser()
config.read("config.ini")

log_file = config.get("LOGGING", "LOG_FILE", fallback="/tmp/baasha-service-api.log")
log_level_str = config.get("LOGGING", "LOG_LEVEL", fallback="INFO")

log_level = getattr(logging, log_level_str.upper(), logging.INFO)


logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        TimedRotatingFileHandler(log_file, when="midnight", interval=1, backupCount=7),
        logging.StreamHandler(sys.stdout),
    ],
)

if __name__ == "__main__":
    debug = False

    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        debug = True

    load_prod_env(app)

    # load voices
    # VoiceResource.preload_voices()

    app.run(debug=debug, host="0.0.0.0")
