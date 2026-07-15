name: AI Stock Photo Generator

permissions:
  contents: write

on:
  schedule:
    - cron: '0 4 * * *'
  workflow_dispatch:
    inputs:
      regenerate:
        description: 'Space-separated filenames to regenerate (e.g. people_reading_hands_1.png)'
        required: false
        default: ''

  push:
    branches: [main]
    paths:
      - 'scripts/**'
      - '.github/workflows/**'

jobs:
  generate-images:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      # generate_pollinations.py + regenerate.py use only stdlib — no pip needed.

      - name: Regenerate specific images (if requested)
        if: ${{ github.event.inputs.regenerate != '' }}
        run: |
          mkdir -p images api
          python scripts/regenerate.py ${{ github.event.inputs.regenerate }}

      - name: Generate new images
        run: |
          mkdir -p images api
          python scripts/generate_pollinations.py

      - name: Commit changes
        run: |
          git config user.email "action@github.com"
          git config user.name "GitHub Action"
          git add images/ api/images.json
          TIMESTAMP=$(date +'%Y-%m-%d %H:%M')
          git commit -m "Generated stock photos - $TIMESTAMP" || exit 0
          git push

  deploy-pages:
    needs: generate-images
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}

    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: '.'
      - id: deployment
        uses: actions/deploy-pages@v4
