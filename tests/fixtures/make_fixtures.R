#!/usr/bin/env Rscript
# Generates the toy Seurat .rds fixture consumed by the Python test suite
# (via rpy2) to exercise BIWT's .rds import code path.
#
# Run from the repo root: Rscript tests/fixtures/make_fixtures.R
# CI regenerates this fresh on every run (see ci.yml) so it always matches
# whatever R/Bioconductor versions the conda env resolved to.

suppressMessages({
  library(Seurat)
})

set.seed(1)

out_dir <- "tests/fixtures"
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

counts <- matrix(rpois(5 * 10, lambda = 5), nrow = 5, ncol = 10)
rownames(counts) <- paste0("Gene", 1:5)
colnames(counts) <- paste0("Cell", 1:10)

coldata <- data.frame(group = rep(c("A", "B"), 5), row.names = colnames(counts))

# --- Seurat ---
seu <- CreateSeuratObject(counts = counts, meta.data = coldata)
saveRDS(seu, file.path(out_dir, "toy_seurat.rds"))

cat("Wrote fixtures to", out_dir, "\n")
