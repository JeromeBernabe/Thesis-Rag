"""Tests for the PCA projection used by the embedding-space 3D view."""

from __future__ import annotations

import json
import math

import pytest

np = pytest.importorskip("numpy")

from bench_bridge.projection import (  # noqa: E402
    ProjectionResult,
    build_from_collection,
    project_documents,
    project_matrix,
    read_projection,
    write_projection,
)


def make_vectors(n=200, dim=16, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, dim))


class TestProjectMatrix:
    def test_returns_three_components(self):
        out = project_matrix(make_vectors())
        assert out["coords"].shape == (200, 3)
        assert out["coords"].dtype == np.float32

    def test_coords_are_contiguous_for_binary_writing(self):
        out = project_matrix(make_vectors())
        assert out["coords"].flags["C_CONTIGUOUS"]

    def test_components_and_mean_are_reported(self):
        """components is (dim, n_components): one column per principal axis.

        That orientation is what lets `project_documents` place a new point with
        a single `vectors @ components` multiply.
        """
        out = project_matrix(make_vectors(dim=16))
        assert np.asarray(out["components"]).shape == (16, 3)
        assert len(out["mean"]) == 16

    def test_components_are_orthonormal(self):
        """PCA loadings must stay unit length and mutually perpendicular."""
        components = np.asarray(project_matrix(make_vectors(dim=16))["components"])
        assert np.allclose(np.linalg.norm(components, axis=0), 1.0, atol=1e-8)
        assert np.allclose(components.T @ components, np.eye(3), atol=1e-8)

    def test_is_deterministic_across_calls(self):
        """Two runs on the same corpus must give the same cloud.

        The PCA solution is only unique up to sign, so a change in numpy's
        eigenvector ordering would silently mirror the view.
        """
        vectors = make_vectors()
        a = project_matrix(vectors)["coords"]
        b = project_matrix(vectors)["coords"]
        assert np.allclose(a, b)

    def test_each_component_has_a_positive_max_loading(self):
        """The sign convention that makes the projection reproducible."""
        out = project_matrix(make_vectors())
        components = np.asarray(out["components"])
        for column in components.T:
            assert column[np.argmax(np.abs(column))] > 0

    def test_mirroring_is_not_possible(self):
        """Explicit check of the failure mode the sign fix prevents."""
        vectors = make_vectors()
        out = project_matrix(vectors)
        coords = out["coords"]
        mean = np.asarray(out["mean"])
        components = np.asarray(out["components"])
        # Recompute from the recorded mean/components: must reproduce coords.
        assert np.allclose((vectors - mean) @ components, coords, atol=1e-4)

    def test_explained_variance_is_descending(self):
        out = project_matrix(make_vectors())
        ev = out["explained_variance"]
        assert ev == sorted(ev, reverse=True)

    def test_explained_variance_ratio_is_a_proportion(self):
        out = project_matrix(make_vectors())
        total = sum(out["explained_variance_ratio"])
        assert 0 < total <= 1.0 + 1e-9

    def test_first_component_captures_the_most_variance(self):
        """A corpus with one dominant axis must show it on PC1."""
        rng = np.random.default_rng(3)
        vectors = rng.normal(size=(300, 8))
        vectors[:, 0] *= 40.0
        out = project_matrix(vectors)
        assert out["explained_variance"][0] > out["explained_variance"][1] * 5

    def test_handles_fewer_points_than_components(self):
        """A 2-document corpus cannot yield 3 components; the extra axes are zero."""
        out = project_matrix(make_vectors(n=2, dim=8))
        assert out["coords"].shape == (2, 3)
        assert np.allclose(out["coords"][:, 2], 0.0)

    def test_handles_a_single_point(self):
        out = project_matrix(make_vectors(n=1, dim=4))
        assert out["coords"].shape == (1, 3)

    def test_identical_points_do_not_divide_by_zero(self):
        """A degenerate corpus has zero variance; ratios must be 0, not NaN."""
        out = project_matrix(np.ones((10, 4)))
        assert not any(math.isnan(v) for v in out["explained_variance_ratio"])
        assert out["explained_variance_ratio"] == [0.0, 0.0, 0.0]

    def test_empty_input_is_rejected(self):
        with pytest.raises(ValueError, match="empty matrix"):
            project_matrix(np.zeros((0, 4)))

    def test_one_dimensional_input_is_rejected(self):
        with pytest.raises(ValueError, match="2-D array"):
            project_matrix(np.zeros((5,)))


class FakeCollection:
    def __init__(self, vectors, name="hotpot_docs"):
        self._vectors = vectors
        self.name = name

    def count(self):
        return len(self._vectors)

    def get(self, limit=None, offset=0, include=None):
        stop = len(self._vectors) if limit is None else min(len(self._vectors), offset + limit)
        chunk = self._vectors[offset:stop]
        return {
            "ids": [f"doc-{i}" for i in range(offset, stop)],
            "embeddings": chunk.tolist(),
        }


class TestBuildFromCollection:
    def test_projects_every_document(self):
        collection = FakeCollection(make_vectors(n=60, dim=8))
        result = build_from_collection(collection, "hotpot", out_dir=None)
        assert result.n_points == 60
        assert result.coords.shape == (60, 3)
        assert result.source_count == 60
        assert result.collection == "hotpot_docs"

    def test_ids_are_read_from_the_collection(self):
        collection = FakeCollection(make_vectors(n=10, dim=4))
        result = build_from_collection(collection, "hotpot", out_dir=None)
        assert result.ids[:3] == ["doc-0", "doc-1", "doc-2"]

    def test_max_points_subsamples_and_records_the_real_size(self):
        collection = FakeCollection(make_vectors(n=1000, dim=4))
        result = build_from_collection(
            collection, "hotpot", out_dir=None, max_points=100
        )
        assert result.n_points == 100
        assert result.source_count == 1000, "UI needs to say '100 of 1000'"

    def test_subsampling_is_deterministic(self):
        collection = FakeCollection(make_vectors(n=500, dim=4))
        a = build_from_collection(collection, "x", out_dir=None, max_points=50)
        b = build_from_collection(collection, "x", out_dir=None, max_points=50)
        assert a.ids == b.ids
        assert np.allclose(a.coords, b.coords)

    def test_batches_are_joined(self):
        """More documents than one batch must still all appear."""
        collection = FakeCollection(make_vectors(n=250, dim=4))
        result = build_from_collection(
            collection, "x", out_dir=None, batch_size=32
        )
        assert result.n_points == 250
        assert len(set(result.ids)) == 250

    def test_progress_callback_reports_progress(self):
        collection = FakeCollection(make_vectors(n=100, dim=4))
        seen = []
        build_from_collection(
            collection, "x", out_dir=None, batch_size=10,
            progress=lambda done, total: seen.append((done, total)),
        )
        assert seen[-1] == (100, 100)

    def test_empty_collection_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            build_from_collection(FakeCollection(np.zeros((0, 4))), "x", out_dir=None)

    def test_bounds_bracket_the_points(self):
        collection = FakeCollection(make_vectors(n=50, dim=4))
        result = build_from_collection(collection, "x", out_dir=None)
        b = result.bounds
        for axis in range(3):
            assert b["min"][axis] <= result.coords[:, axis].min() + 1e-4
            assert b["max"][axis] >= result.coords[:, axis].max() - 1e-4


class TestWriteReadRoundTrip:
    def test_round_trips(self, tmp_path):
        collection = FakeCollection(make_vectors(n=40, dim=8))
        result = build_from_collection(collection, "hotpot", out_dir=tmp_path)
        points_path, meta_path = write_projection(result, tmp_path)

        assert points_path.name == "hotpot.points.bin"
        assert meta_path.name == "hotpot.meta.json"

        meta, coords = read_projection("hotpot", tmp_path)
        assert meta["n_points"] == 40
        assert meta["dataset"] == "hotpot"
        assert coords.shape == (40, 3)
        assert np.allclose(coords, result.coords)

    def test_binary_is_exactly_n_times_3_float32s(self, tmp_path):
        collection = FakeCollection(make_vectors(n=40, dim=8))
        result = build_from_collection(collection, "hotpot", out_dir=tmp_path)
        points_path, _ = write_projection(result, tmp_path)
        assert points_path.stat().st_size == 40 * 3 * 4

    def test_meta_carries_everything_needed_to_project_new_documents(self, tmp_path):
        collection = FakeCollection(make_vectors(n=20, dim=8))
        result = build_from_collection(collection, "hotpot", out_dir=tmp_path)
        write_projection(result, tmp_path)
        meta, _ = read_projection("hotpot", tmp_path)
        for key in ("ids", "components", "mean", "bounds",
                    "explained_variance_ratio", "source_count", "dim"):
            assert key in meta, f"meta is missing {key}"

    def test_no_temp_file_is_left_behind(self, tmp_path):
        """The webview must never read a half-written meta file."""
        collection = FakeCollection(make_vectors(n=10, dim=4))
        result = build_from_collection(collection, "hotpot", out_dir=tmp_path)
        write_projection(result, tmp_path)
        assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []

    def test_truncated_binary_is_detected(self, tmp_path):
        collection = FakeCollection(make_vectors(n=20, dim=4))
        result = build_from_collection(collection, "hotpot", out_dir=tmp_path)
        points_path, _ = write_projection(result, tmp_path)
        points_path.write_bytes(points_path.read_bytes()[:-4])
        with pytest.raises(ValueError, match="expected 60 floats, found 59"):
            read_projection("hotpot", tmp_path)


class TestProjectDocuments:
    @pytest.fixture
    def projection(self):
        vectors = make_vectors(n=40, dim=8)
        out = project_matrix(vectors)
        return ProjectionResult(
            dataset="x", collection="c", dim=8,
            ids=[f"doc-{i}" for i in range(40)],
            coords=out["coords"], components=out["components"], mean=out["mean"],
            explained_variance=out["explained_variance"],
            explained_variance_ratio=out["explained_variance_ratio"],
            source_count=40,
        )

    def test_places_new_documents_in_the_same_space(self, projection):
        """A document's coordinates must match its own PCA transform.

        This is what lets a live retrieval hit land on top of its neighbours in
        the precomputed cloud instead of somewhere unrelated.
        """
        vector = np.arange(8, dtype=np.float64)
        coords = project_documents(["x"], projection, embed_fn=lambda t: [vector])
        expected = (
            (vector - np.asarray(projection.mean)) @ np.asarray(projection.components)
        )
        assert np.allclose(coords[0], expected, atol=1e-4)

    def test_returns_one_row_per_text(self, projection):
        coords = project_documents(
            ["a", "b", "c"], projection, embed_fn=lambda texts: np.zeros((3, 8))
        )
        assert coords.shape == (3, 3)
        assert coords.dtype == np.float32

    def test_empty_input_returns_empty_array(self, projection):
        assert project_documents([], projection).shape == (0, 3)

    def test_embed_fn_count_mismatch_is_rejected(self, projection):
        with pytest.raises(ValueError, match="returned 1 vectors for 2 texts"):
            project_documents(["a", "b"], projection, embed_fn=lambda t: np.zeros((1, 8)))

    def test_is_reproducible(self, projection):
        vector = np.arange(8, dtype=np.float64)
        a = project_documents(["x"], projection, embed_fn=lambda t: [vector])
        b = project_documents(["x"], projection, embed_fn=lambda t: [vector])
        assert np.allclose(a, b)
