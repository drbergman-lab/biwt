# Troubleshooting

Almost everything on this page is about `.rds` import. CSV and `.h5ad` rarely go wrong, and
when they do the error message says what is wrong with the file.

!!! tip "One root cause explains most of it"
    **`rpy2` is using the wrong R.** It picks its R from `$R_HOME`, and only falls back to
    the first `R` on `$PATH` when that is unset. On macOS another R installation is often
    reachable earlier on `PATH` (for example, by a symlink in `/usr/local/bin`), so if the
    active conda environment has no R of its own — or `R_HOME` is unset — `rpy2` can silently
    bind to that system R instead of the conda one.

    Mixing conda-Python with a non-conda R is what produces the segfault (#3) and the OpenMP
    error (#4). Setting `R_HOME` to the environment's own R resolves the majority of these
    problems at once.

## Quick diagnostics

Run these first. They will usually tell you which of the numbered problems below you have.

```bash
# Which R will rpy2 actually use? Should print a path INSIDE the active env.
python -c "import rpy2.situation as s; print(s.get_r_home())"
python -m rpy2.situation                     # fuller rpy2/R report

# Which executables resolve, and in what order?
which python                                 # expect the conda env's python
which R; type -a R                           # watch for a system R, e.g. /usr/local/bin/R
echo "$PATH"

# Confirm the active environment
echo "$CONDA_PREFIX"; echo "$CONDA_SHLVL"
conda env config vars list                   # is R_HOME pinned for this env?
```

On macOS, to see which OpenMP libraries get loaded when the host application starts:

```bash
DYLD_PRINT_LIBRARIES=1 python <your-host-launch-command> 2>&1 | grep -i libomp
```

## 1. conda cannot solve `anndata2ri`

**Symptom**

```
nothing provides get_version needed by anndata2ri-1.3.2
```

**Cause.** `conda-forge` (and/or `bioconda`) was not enabled, so conda could not resolve a
transitive dependency of the `anndata2ri` conda package.

**Fix.** Prefer installing `anndata2ri` via **pip** — `pip install "biwt[seurat]"` pulls a
correctly pinned `anndata2ri<2`. If you must use conda, enable both channels:

```bash
conda install -c conda-forge -c bioconda anndata2ri
```

## 2. `rpy2` binds to the wrong R

**Symptom.** `python -m rpy2.situation` reports
`Calling 'R RHOME': /Library/Frameworks/R.framework/Resources` even though `r-base` is
installed in the conda environment; and/or `which R` gives `/usr/local/bin/R`.

**Cause.** `R_HOME` is unset, so `rpy2` resolves `R` from `PATH`, where a system R is found
before — or instead of — the conda R.

**Fix.** Pin `R_HOME` to the environment's R. Scoped to the env, re-applied on every
activation, no global PATH edits:

```bash
conda env config vars set R_HOME="$CONDA_PREFIX/lib/R"
conda deactivate && conda activate <env>
```

Verify with the first diagnostic command — it should now print a path inside the env.

## 3. `substring` error then segmentation fault

**Symptom**

```
Error in substring(x, m + 1L) : invalid substring arguments
Segmentation fault
```

...crashing the host application outright.

**Cause.** `rpy2` embedded a **different R than it was built against** — typically conda's
`rpy2` loading a system R (see [#2](#2-rpy2-binds-to-the-wrong-r)). The ABI mismatch corrupts
R initialization, surfacing as the `substring` error and then a segfault. The OpenMP clash in
[#4](#4-duplicate-openmp-runtime) is a related symptom of the same mixing.

**Fix.** Make `rpy2` use the matching conda R by setting `R_HOME` (#2). Also install `r-base`
**and** `rpy2` from conda *before* `pip install "biwt[seurat]"`, so `rpy2` is the conda build
that is ABI-matched to conda's R. Never let pip compile `rpy2` against the system R.

## 4. Duplicate OpenMP runtime

**Symptom**

```
OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib already initialized.
```

**Cause.** Two OpenMP runtimes in one process — conda-Python's `libomp.dylib` plus the one
the embedded non-conda R links against.

**Fix.** Use a single R stack. With `rpy2` pointed at the **conda** R (#2), the embedded R
shares conda's `libomp` and the clash disappears. Avoid embedding a non-conda R inside a
conda-Python process.

!!! danger "`KMP_DUPLICATE_LIB_OK=TRUE` is not a fix"
    It silences the message but is a last resort — it can mask crashes or produce wrong
    results. Fix the R mismatch instead.

## 5. Missing Seurat R packages

**Symptom**

```
Failed to read '<file>.rds' as R object: ... unable to load required package 'SeuratObject'
```

**Cause.** The R that `rpy2` uses does not have the Seurat R packages installed. Reading a
Seurat `.rds` needs `SeuratObject` just to reconstruct the object's classes, plus `Seurat` and
`SingleCellExperiment` for the conversion to AnnData.

**Fix.** Install the R packages into the *same* R that `rpy2` uses — confirm which one that is
with the first diagnostic before installing anything. Prefer conda's prebuilt binaries:

```bash
conda install -c conda-forge -c bioconda r-seurat bioconductor-singlecellexperiment
```

If those binaries aren't available for your platform, fall back to CRAN/Bioconductor. This
compiles from source and is slow:

```bash
R -e 'install.packages("Seurat", repos="https://cloud.r-project.org")'
R -e 'if (!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager", repos="https://cloud.r-project.org"); BiocManager::install("SingleCellExperiment", update=FALSE, ask=FALSE)'
```

## 6. `anndata2ri` has no `activate()`

**Symptom**

```
module 'anndata2ri' has no attribute 'activate'
```

or `anndata2ri activation failed: ...` when loading an `.rds` / `.rda`.

**Cause.** `anndata2ri` **2.0+** is installed. The `activate()` API BIWT uses exists
throughout the `1.x` line but was removed in the 2.0 rewrite; BIWT requires `anndata2ri < 2`.
This usually happens when 2.0 gets pulled in by an unpinned `conda install anndata2ri` over
BIWT's requirement.

**Fix.** Pin to the 1.x line:

```bash
pip install "anndata2ri<2"
```

Installing via `pip install "biwt[seurat]"` already enforces this — just don't override it
with a newer conda build afterwards.

---

## Root-cause summary

1. **Wrong R (the big one).** `R_HOME` unset → `rpy2` uses a system R from `PATH` instead of
   the conda R. Causes #2, #3, and #4. Fixed by pinning `R_HOME`.
2. **pip-built `rpy2`.** Letting pip compile `rpy2` links it against the system R. Install
   `r-base` + `rpy2` from conda first so they are ABI-matched.
3. **Channel / version hygiene.** Missing `conda-forge`/`bioconda` (#1) and unpinned
   `anndata2ri` 2.0 (#6). Prefer `pip install "biwt[seurat]"`, which pins dependencies.

## Still stuck?

Open an issue at
[github.com/drbergman-lab/biwt/issues](https://github.com/drbergman-lab/biwt/issues) with the
output of `python -m rpy2.situation` and the full error text.
