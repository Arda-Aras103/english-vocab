# English–Turkish Vocabulary Dictionary

Fast, offline-first personal English–Turkish dictionary (**1,950+** entries) built from a single Markdown file (`vocabulary.md`) into a zero-dependency static web app via GitHub Pages.

## Features
- Split-pane dictionary layout (instant search `/` + `↑`/`↓` keyboard navigation)
- Turkish-character-friendly search across headwords, meanings, collocations, and examples
- Built-in English pronunciation (`speechSynthesis`) & Dark/Light warm editorial theme
- Automatic GitHub Pages rebuild on every push to `main`

## Adding Words
Edit `vocabulary.md` directly (locally or via GitHub web UI) and push to `main` — GitHub Actions automatically rebuilds and publishes the site in ~15 seconds.

To preview locally:
```bash
python3 build.py --normalize --input vocabulary.md --output index.html
```
