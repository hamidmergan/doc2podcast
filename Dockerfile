FROM python:3.12-slim

# ffmpeg joins the voiced contributions into one MP3. git lets pip fetch the sibling
# tool doc2speech, which is named with its repository in pyproject.toml.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[ui]" \
    && useradd --create-home --uid 1000 app

USER app
EXPOSE 8000

# The web page: drop documents, pick the cast, check the script, get an MP3 back.
# Settings come from DOC2PODCAST_* environment variables, for example
# DOC2PODCAST_BASE_URL, DOC2PODCAST_MODEL, DOC2PODCAST_TTS_MODEL and
# DOC2PODCAST_VOICES. They can also be typed into the page.
CMD ["doc2podcast", "serve", "--host", "0.0.0.0", "--port", "8000"]
