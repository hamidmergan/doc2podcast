# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-23

### Added

- Episode script from PDF, DOCX, PPTX, TXT, MD, SRT and VTT files: the material is
  planned first, then written part by part, so a long episode stays one conversation.
- One to four speakers with their own names, roles and voices, in English or German,
  in a teaching, casual or interview tone.
- Length in minutes, turned into a number of contributions.
- `write_script`, `render` and `make_podcast` as the library API.
- CLI `doc2podcast` with `--script-only` for a script to review and `--from-script`
  to voice a reviewed one.
- Markdown script format with the cast and the settings in the head, readable and
  writable by hand.
- Voicing of every contribution through an OpenAI-compatible speech model, with the
  pieces levelled and joined by ffmpeg, and a gap between them that fits the moment.
- Own settings for the speech side, with a fallback to the chat values.
- `--instructions` for a wish about subject or tone, and `--intro-note` for a spoken
  note that also lands in the metadata of the file.
