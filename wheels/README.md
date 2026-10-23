# Local wheels

Put wheels here that pip should prefer over the index when the image is built.
Wheels you drop in stay out of version control.

Right now one wheel is required, because doc2speech is not on a package index yet and
the image build would fail at the resolver without it:

```bash
pip wheel --no-deps -w wheels ../doc2speech
```

Run that once from the repository root, with your doc2speech checkout next to it. Then
`docker compose build` works.
