"""paper-radar command line interface.

Stages:
    ingest   -- pull URLs (+ light metadata) from exported Teams PDFs into the DB
    enrich   -- summarize/tag papers with Claude (implemented separately; stub)
    embed    -- compute local embeddings, build the FAISS index, save UMAP coords
    serve    -- launch the Streamlit app
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from .config import get_settings
from .db import get_session, init_db
from .models import Paper

app = typer.Typer(help="Paper discovery + recommendation for a single lab.", no_args_is_help=True)


@app.command()
def ingest(
    pdf_dir: Path = typer.Argument(..., help="Directory of PDFs exported from Teams."),
    fetch_metadata: bool = typer.Option(
        True, help="Look up title/authors/year from arXiv/Crossref for each URL."
    ),
) -> None:
    """Extract URLs from PDFs and add new papers to the database."""
    from .ingest.metadata import fetch_metadata as _fetch_metadata
    from .ingest.pdf_extract import extract_urls_from_dir, parse_posted_at

    if not pdf_dir.exists():
        typer.secho(f"No such directory: {pdf_dir}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    init_db()
    found = extract_urls_from_dir(pdf_dir)
    typer.echo(f"Found {len(found)} unique URL(s) across PDFs in {pdf_dir}.")

    added = 0
    enriched = 0
    label = "Fetching metadata" if fetch_metadata else "Saving"
    with get_session() as session:
        from sqlmodel import select

        with typer.progressbar(found, label=label) as progress:
            for item in progress:
                exists = session.exec(select(Paper).where(Paper.url == item.url)).first()
                if exists is not None:
                    continue
                paper = Paper(
                    url=item.url,
                    posted_by=item.posted_by,
                    posted_at=parse_posted_at(item.posted_at),
                )
                if fetch_metadata:
                    try:
                        meta = _fetch_metadata(item.url)
                    except Exception:  # never let one bad URL abort the whole run
                        meta = None
                    if meta is not None:
                        paper.title = meta.title
                        paper.authors = meta.authors
                        paper.venue = meta.venue
                        paper.year = meta.year
                        paper.doi = meta.doi
                        paper.abstract = meta.abstract
                        paper.keywords = meta.keywords
                        if meta.title:
                            enriched += 1
                session.add(paper)
                added += 1
        session.commit()

    typer.secho(f"Added {added} new paper(s).", fg=typer.colors.GREEN)
    if fetch_metadata:
        typer.secho(f"Resolved metadata (title) for {enriched} of {added}.", fg=typer.colors.GREEN)


@app.command()
def enrich(
    limit: int = typer.Option(0, help="Max papers to enrich (0 = all un-enriched)."),
) -> None:
    """Enrich papers with Claude (summary, tags, code/data links).

    The enrichment logic lives in ``paper_radar/enrich/agent.py`` and is a stub
    you implement yourself; this command wires it to the database.
    """
    from sqlmodel import select

    from .enrich.agent import apply_enrichment, enrich_paper

    init_db()
    with get_session() as session:
        query = select(Paper).where(Paper.summary.is_(None))  # type: ignore[union-attr]
        papers = list(session.exec(query).all())
        if limit:
            papers = papers[:limit]
        if not papers:
            typer.echo("Nothing to enrich.")
            return
        for paper in papers:
            try:
                grounding = paper.abstract or paper.title or paper.url
                enrichment = enrich_paper(paper, source_text=grounding)
                apply_enrichment(paper, enrichment)
                session.add(paper)
            except NotImplementedError:
                typer.secho(
                    "enrich/agent.py is still a stub -- implement enrich_paper().",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
                raise typer.Exit(2) from None
        session.commit()
    typer.secho(f"Enriched {len(papers)} paper(s).", fg=typer.colors.GREEN)


@app.command()
def embed(
    rebuild: bool = typer.Option(True, help="Rebuild the index from scratch."),
) -> None:
    """Embed papers, build the FAISS index, and save UMAP 2-D coordinates."""
    import numpy as np
    from sqlmodel import select

    from .embed.embed import embed_papers
    from .embed.index import build_index, compute_umap, save_index

    settings = get_settings()
    init_db()
    with get_session() as session:
        papers = list(session.exec(select(Paper)).all())
        if not papers:
            typer.secho("No papers in the DB yet -- run `ingest` first.", fg=typer.colors.YELLOW)
            raise typer.Exit(0)

        typer.echo(f"Embedding {len(papers)} paper(s) with {settings.embedding_model} ...")
        vecs = embed_papers(papers)

        index = build_index(vecs)
        save_index(index, settings.faiss_index_path)

        for row_id, paper in enumerate(papers):
            paper.embedding_id = row_id
            session.add(paper)
        session.commit()

        coords = compute_umap(vecs)
        settings.umap_coords_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(settings.umap_coords_path, coords)

    typer.secho(
        f"Wrote index -> {settings.faiss_index_path} and UMAP coords -> "
        f"{settings.umap_coords_path}",
        fg=typer.colors.GREEN,
    )


@app.command()
def serve(
    port: int = typer.Option(8501, help="Port for the Streamlit server."),
) -> None:
    """Launch the Streamlit app."""
    app_path = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)]
    typer.echo("Launching: " + " ".join(cmd))
    raise typer.Exit(subprocess.call(cmd))


if __name__ == "__main__":
    app()
