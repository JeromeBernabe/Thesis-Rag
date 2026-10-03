"""PCA projection of a ChromaDB collection down to 3 dimensions.

Output format
-------------
Two files, both written under ``data/bench/projections/``::

    <dataset>.points.bin   little-endian float32, n_points * 3, no header
    <dataset>.meta.json    ids, component vectors, mean, bounds, explained var

``.points.bin`` is a bare array of floats rather than JSON because the FinTech
corpus has 6,251 points and the hotpot/math corpora have ~30,000: JSON for 90,000
floats is roughly 1.8 MB of text to parse on every page load, whereas the binary
is 360 KB and ``readFile``/``DataView`` handles it directly. The webview reads
the binary with a ``Float32Array`` view, so there is no parsing cost at all.

Why PCA and not UMAP/t-SNE
---------------------------
UMAP/t-SNE distort global distances and are not deterministic across runs, which
would make the "same corpus, different run" comparison meaningless. PCA on
mean-centred embeddings is deterministic (given a fixed sign convention),
preserves global structure, and its explained variance is reported so the view
can honestly say how much information the 3 axes retain. For 768-dim
sentence-transformer vectors, 3 components typically retain only ~10-20% of
variance, so the UI labels the axis as indicative rather than exact.

Determinism
-----------
SVD sign is arbitrary, so each component's sign is flipped to make its largest
absolute loading positive. Without this, two runs of the same corpus would
produce mirrored clouds and a user comparing two runs would think the embedding
had changed when it had not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "ProjectionResult",
    "project_matrix",
    "write_projection",
    "read_projection",
    "build_from_collection",
]

N_COMPONENTS = 3


@dataclass
class ProjectionResult:
    """A 3D projection plus everything needed to reproduce and explain it.

    ``components`` has shape ``(dim, n_components)`` - one column per axis, each
    column being that principal direction expressed over the original embedding
    dimensions. It is stored transposed relative to the usual textbook layout
    because that is the orientation ``vectors @ components`` needs in order to
    project new points with a single matrix multiply.
    """

    dataset: str
    collection: str
    dim: int
    ids: list[str]
    coords: Any  # numpy.ndarray, shape (n_points, 3), float32
    components: list[list[float]]
    mean: list[float]
    explained_variance: list[float]
    explained_variance_ratio: list[float]
    source_count: int

    @property
    def n_points(self) -> int:
        return len(self.ids)

    @property
    def bounds(self) -> dict[str, list[float]]:
        """Axis-aligned min/max per dimension, for framing the camera."""
        if self.coords.size == 0:
            return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}
        mins = self.coords.min(axis=0)
        maxs = self.coords.max(axis=0)
        return {"min": mins.tolist(), "max": maxs.tolist()}

    def meta(self) -> dict:
        return {
            "schema_version": 1,
            "dataset": self.dataset,
            "collection": self.collection,
            "dim": self.dim,
            "n_points": self.n_points,
            "source_count": self.source_count,
            "ids": self.ids,
            "components": self.components,
            "mean": self.mean,
            "explained_variance": self.explained_variance,
            "explained_variance_ratio": self.explained_variance_ratio,
            "bounds": self.bounds,
        }


def _center(vectors):
    import numpy as np

    mean = vectors.mean(axis=0)
    return vectors - mean, mean


def _fix_signs(components):
    """Flip each column so its largest-magnitude loading is positive.

    Makes the projection reproducible: SVD/eigh is only defined up to sign, so
    two runs would otherwise produce mirrored clouds.

    ``components`` is ``(dim, k)``, so each principal direction is a *column*.
    """
    import numpy as np

    fixed = np.array(components, dtype=np.float64, copy=True)
    for i in range(fixed.shape[1]):
        loading = fixed[:, i]
        if loading.size == 0:
            continue
        idx = int(np.argmax(np.abs(loading)))
        if loading[idx] < 0:
            fixed[:, i] = -loading
    return fixed


def project_matrix(vectors, n_components: int = N_COMPONENTS) -> dict[str, Any]:
    """Project a ``(n, dim)`` matrix to ``n_components`` dimensions via PCA.

    Returns a dict with ``coords`` ``(n, n_components)``, ``components``
    ``(dim, n_components)``, ``mean`` ``(dim,)`` and the explained variance.

    Three degenerate shapes are handled explicitly, because they all occur for
    real corpora and a NaN here would poison the 3D view rather than raise:

    * ``n > n_components``: the normal case. The eigendecomposition of the
      ``(dim, dim)`` covariance is used, which avoids materialising the
      ``(n, n)`` Gram matrix an SVD would need - at n=30,000 that is 7.2 GB.
    * ``n <= n_components`` (e.g. a 2-document corpus): the covariance has rank
      ``n - 1``, so the remaining axes are zero-filled and the view shows a flat
      slab, which is correct rather than an error.
    * ``n == 1``: the sample covariance is undefined (0 degrees of freedom), so
      it is taken as zero and every point sits at the origin.
    """
    import numpy as np

    vectors = np.asarray(vectors, dtype=np.float64)
    if vectors.ndim != 2:
        raise ValueError(f"expected a 2-D array, got shape {vectors.shape}")
    n, dim = vectors.shape
    if n == 0:
        raise ValueError("cannot project an empty matrix")

    centered, mean = _center(vectors)

    if n == 1:
        # np.cov would return NaN here; a single point is the origin by definition.
        return {
            "coords": np.zeros((1, n_components), dtype=np.float32),
            "components": np.eye(dim, n_components, dtype=np.float64).tolist(),
            "mean": mean.tolist(),
            "explained_variance": [0.0] * n_components,
            "explained_variance_ratio": [0.0] * n_components,
            "dim": dim,
        }

    k = min(n - 1, n_components)
    covariance = np.cov(centered, rowvar=False)
    covariance = np.atleast_2d(covariance)
    covariance = np.nan_to_num(covariance, nan=0.0, posinf=0.0, neginf=0.0)

    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    # eigh returns ascending; take the largest k and reverse.
    order = np.argsort(eigenvalues)[::-1][:k]
    eigenvalues = np.clip(eigenvalues[order], 0.0, None)
    components = _fix_signs(eigenvectors[:, order])  # (dim, k)

    scores = centered @ components
    if k < n_components:
        # Rank-deficient: pad the unused axes with zeros.
        scores = np.hstack([scores, np.zeros((n, n_components - k))])
        components = np.hstack([components, np.zeros((dim, n_components - k))])

    total_variance = float(eigenvalues.sum())
    ratio = [0.0] * n_components
    if total_variance > 0:
        for i in range(k):
            ratio[i] = float(eigenvalues[i] / total_variance)

    return {
        "coords": np.ascontiguousarray(scores, dtype=np.float32),
        "components": components.tolist(),
        "mean": mean.tolist(),
        "explained_variance": eigenvalues.tolist(),
        "explained_variance_ratio": ratio,
        "dim": dim,
    }


def write_projection(result: ProjectionResult, out_dir: Path) -> tuple[Path, Path]:
    """Write ``<dataset>.points.bin`` and ``<dataset>.meta.json``.

    Returns ``(points_path, meta_path)``. The binary is written with an explicit
    little-endian dtype so the file is byte-identical regardless of host
    endianness, and the meta records the element count so a truncated file is
    detectable.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    points_path = out_dir / f"{result.dataset}.points.bin"
    meta_path = out_dir / f"{result.dataset}.meta.json"

    coords = result.coords
    # <f4 makes numpy emit little-endian regardless of platform byte order.
    coords.astype("<f4").tofile(points_path)

    meta = result.meta()
    tmp = meta_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
    tmp.replace(meta_path)  # atomic: the webview never reads a half-written file

    return points_path, meta_path


def read_projection(
    dataset: str, out_dir: Path
) -> tuple[dict, Any]:
    """Load a projection written by :func:`write_projection`.

    Returns ``(meta, coords)`` where ``coords`` is a float32 ``(n, 3)`` array.
    """
    import numpy as np

    out_dir = Path(out_dir)
    points_path = out_dir / f"{dataset}.points.bin"
    meta_path = out_dir / f"{dataset}.meta.json"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected = int(meta["n_points"]) * 3
    raw = np.fromfile(points_path, dtype="<f4")
    if raw.size != expected:
        raise ValueError(
            f"{points_path.name}: expected {expected} floats, found {raw.size}"
        )
    return meta, raw.reshape(-1, 3)


def iter_collection_batches(collection, batch_size: int = 2000) -> Iterable[Any]:
    """Yield ``(ids, embeddings)`` batches from a Chroma collection.

    Chroma's ``get`` returns dicts, so this is wrapped to yield the tuple form
    the rest of the module expects and to keep the memory ceiling at one batch
    regardless of corpus size.
    """
    total = collection.count()
    offset = 0
    while offset < total:
        batch = collection.get(limit=batch_size, offset=offset, include=["embeddings"])
        ids = batch.get("ids") or []
        embeddings = batch.get("embeddings")
        if not ids or embeddings is None:
            break
        yield ids, embeddings
        offset += len(ids)


def build_from_collection(
    collection,
    dataset: str,
    out_dir: Path,
    max_points: int | None = None,
    batch_size: int = 2000,
    progress=None,
) -> ProjectionResult:
    """Build and persist a 3D projection for one Chroma collection.

    ``max_points`` subsamples deterministically (stride sampling, not random) so
    the interactive view stays responsive on the ~30,000-document corpora while
    remaining a stable subset across runs. ``source_count`` records the true
    corpus size so the UI can say "showing 8,000 of 30,000".
    """
    import numpy as np

    all_ids: list[str] = []
    chunks: list[Any] = []
    source_count = collection.count()

    for ids, embeddings in iter_collection_batches(collection, batch_size=batch_size):
        all_ids.extend(str(i) for i in ids)
        chunks.append(np.asarray(embeddings, dtype=np.float64))
        if progress is not None:
            progress(len(all_ids), source_count)

    if not all_ids:
        raise ValueError(f"collection {dataset!r} is empty")

    matrix = np.vstack(chunks)
    del chunks

    if max_points is not None and len(all_ids) > max_points:
        # Stride sampling keeps the corpus-wide structure; a random draw would
        # need a seeded RNG and would scatter differently between runs.
        stride = max(1, len(all_ids) // max_points)
        idx = np.arange(0, len(all_ids), stride)[:max_points]
        matrix = matrix[idx]
        all_ids = [all_ids[i] for i in idx]

    projected = project_matrix(matrix)
    return ProjectionResult(
        dataset=dataset,
        collection=getattr(collection, "name", dataset),
        dim=projected["dim"],
        ids=all_ids,
        coords=projected["coords"],
        components=projected["components"],
        mean=projected["mean"],
        explained_variance=projected["explained_variance"],
        explained_variance_ratio=projected["explained_variance_ratio"],
        source_count=source_count,
    )


def project_documents(
    texts: Sequence[str],
    projection: ProjectionResult,
    embed_fn=None,
) -> Any:
    """Embed ``texts`` and place them in an existing collection's PCA space.

    Returns an ``(n, 3)`` float32 array. This is how live retrieval results are
    drawn as highlighted points on the same axes as the precomputed cloud: the
    PCA ``mean`` and ``components`` must be reused verbatim, otherwise the
    retrieved chunk would land in a visibly different place from its own
    neighbours in the cloud.

    ``embed_fn`` is injectable so tests can pass a deterministic stub instead of
    requiring a running Ollama.
    """
    import numpy as np

    if not texts:
        return np.zeros((0, 3), dtype=np.float32)

    if embed_fn is None:
        embed_fn = _default_embed_fn

    vectors = np.asarray(embed_fn(list(texts)), dtype=np.float64)
    if vectors.shape[0] != len(texts):
        raise ValueError(
            f"embed_fn returned {vectors.shape[0]} vectors for {len(texts)} texts"
        )

    mean = np.asarray(projection.mean, dtype=np.float64)
    # components is (dim, n_components), which is exactly the orientation
    # `vectors @ components` needs.
    components = np.asarray(projection.components, dtype=np.float64)
    return np.ascontiguousarray((vectors - mean) @ components, dtype=np.float32)


def _default_embed_fn(texts: Sequence[str]) -> Any:
    """Embed with the same model the corpus was built with."""
    from config.settings import EMBED_MODEL
    from langchain_ollama import OllamaEmbeddings

    embedder = OllamaEmbeddings(model=EMBED_MODEL)
    return embedder.embed_documents(list(texts))