#!/usr/bin/env Rscript
# Generates toy Seurat / SingleCellExperiment / SpatialExperiment .rds
# fixtures consumed by the Python test suite (via rpy2) to exercise BIWT's
# .rds import code paths.
#
# Run from the repo root: Rscript tests/fixtures/make_fixtures.R
# CI regenerates these fresh on every run (see ci.yml) so they always match
# whatever R/Bioconductor versions the conda env resolved to.

suppressMessages({
  library(Seurat)
  library(SingleCellExperiment)
  library(SpatialExperiment)
})

set.seed(1)

out_dir <- "tests/fixtures"
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

make_toy_counts <- function() {
  counts <- matrix(rpois(5 * 10, lambda = 5), nrow = 5, ncol = 10)
  rownames(counts) <- paste0("Gene", 1:5)
  colnames(counts) <- paste0("Cell", 1:10)
  counts
}

make_toy_coldata <- function(counts) {
  data.frame(group = rep(c("A", "B"), 5), row.names = colnames(counts))
}

counts <- make_toy_counts()
coldata <- make_toy_coldata(counts)

# --- Seurat ---
seu <- CreateSeuratObject(counts = counts, meta.data = coldata)
saveRDS(seu, file.path(out_dir, "toy_seurat.rds"))

# --- SingleCellExperiment ---
sce <- SingleCellExperiment(assays = list(counts = counts), colData = coldata)
saveRDS(sce, file.path(out_dir, "toy_sce.rds"))

# --- SpatialExperiment ---
spatial_coords <- matrix(
  runif(10 * 2, 0, 100),
  ncol = 2,
  dimnames = list(colnames(counts), c("x", "y"))
)
spe <- SpatialExperiment(
  assays = list(counts = counts),
  colData = coldata,
  spatialCoords = spatial_coords
)
saveRDS(spe, file.path(out_dir, "toy_spatialexperiment.rds"))

cat("Wrote fixtures to", out_dir, "\n")