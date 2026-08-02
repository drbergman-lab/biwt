# Installation

BIWT's core install reads `.csv` and nothing else. Every other format is an optional extra,
because each pulls in a substantially larger dependency stack — there is no reason to make
someone install R to read a spreadsheet.

Python 3.9 or newer is required.

| Install | Adds |
| --- | --- |
| `pip install biwt` | Core — `.csv` import |
| `pip install "biwt[anndata]"` | `.h5ad` (AnnData) import |
| `pip install "biwt[seurat]"` | `.rds` / `.rda` / `.rdata` import — **also needs R, [see below](#seurat-rds-import-optional)** |
| `pip install "biwt[gui]"` | The PyQt5 walkthrough UI |
| `pip install "biwt[all]"` | Everything above |

Extras combine, so the common case is one command:

```bash
pip install "biwt[anndata,gui]"
```

!!! note "If you are using BIWT through a host application"
    Hosts that embed BIWT — such as
    [PhysiCell Studio](https://github.com/PhysiCell-Tools/PhysiCell-Studio) — usually supply
    the GUI dependencies themselves, so installing `biwt[gui]` on top of the host's own Qt
    can cause conflicts. Check the host's documentation for which extras it expects.

## Development install

```bash
git clone https://github.com/drbergman-lab/biwt.git
cd biwt
pip install -e ".[dev]"
```

Run the test suite:

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

The Seurat `.rds` test skips unless R is available and you have generated the fixture with
`Rscript tests/fixtures/make_fixtures.R`. Everything else runs anywhere.

To build this documentation site locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Seurat / `.rds` import (optional)

Reading `.rds` / `.rda` / `.rdata` needs more than a pip extra: it needs a working R with the
`Seurat` and `SingleCellExperiment` R packages, reached through `rpy2`.

The whole R stack — the interpreter, both R packages, and `rpy2` — installs from conda as
**prebuilt binaries**, so it is fast (no source compile) and lands in the environment's own
R, with no dependency on a system-wide R install.

Replace `<env>` with the name of the conda environment you are installing into.

```bash
# 1. Activate your existing environment
conda activate <env>
```

```bash
# 2. Add the R stack from conda (prebuilt binaries; r-seurat pulls r-seuratobject)
conda install -c conda-forge -c bioconda r-base rpy2 r-seurat bioconductor-singlecellexperiment
```

```bash
# 3. Install BIWT with the Seurat extra (adds anndata2ri<2; rpy2 already satisfied by conda)
pip install "biwt[seurat]"

# 4. Point rpy2 at this environment's R (conda re-applies it on every activation)
conda env config vars set R_HOME="$CONDA_PREFIX/lib/R"
conda deactivate && conda activate <env>
```

!!! warning "Step 2 is in its own block on purpose"
    `conda install` prompts `y/n`. If it is pasted together with the commands that follow,
    the next line gets swallowed as the answer to that prompt.

??? info "Why step 4 matters"
    `rpy2` chooses its R from `R_HOME`, falling back to the first `R` on `PATH` when it is
    unset. On macOS a different R installation may sit earlier on `PATH` (for example, one
    reachable by a symlink in `/usr/local/bin`), so without `R_HOME` set `rpy2` can load that
    other R — which lacks Seurat — and segfault. Setting `R_HOME` via `conda env config vars`
    pins it to this environment's own R: scoped to the environment, re-applied on every
    activation, with no global PATH changes.

    The double quotes are load-bearing. Your shell expands `$CONDA_PREFIX` before conda
    stores the value, so conda records an absolute path. That means the value does **not**
    follow the environment — re-run step 4 after moving, renaming, or cloning it.

??? info "Why the order matters"
    Install the conda R stack (step 2) *before* `pip install "biwt[seurat]"` (step 3).
    `anndata2ri` depends on `rpy2`, but neither pulls in R itself — `r-base` is not a pip
    package. If `rpy2` is left to pip, it links against whatever R it finds, which is the
    system R, reproducing the segfault described in
    [troubleshooting #3](troubleshooting.md#3-substring-error-then-segmentation-fault).
    Installing it from conda first gives an `rpy2` that is ABI-matched to conda's R.

??? info "Fallback if the conda binaries are unavailable (slow)"
    If conda has no `r-seurat` / `bioconductor-singlecellexperiment` build for your platform,
    install just `r-base rpy2` from conda in step 2 and get the R packages from
    CRAN/Bioconductor instead. This compiles from source and can take a long time:

    ```bash
    R -e 'install.packages("Seurat", repos="https://cloud.r-project.org")'
    R -e 'if (!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager", repos="https://cloud.r-project.org"); BiocManager::install("SingleCellExperiment", update=FALSE, ask=FALSE)'
    ```

### Check that it worked

```bash
python -c "import rpy2.situation as s; print(s.get_r_home())"
```

This should print a path **inside** your active environment. If it prints something like
`/Library/Frameworks/R.framework/Resources`, `rpy2` has bound to a system R and `.rds` import
will fail — see [troubleshooting #2](troubleshooting.md#2-rpy2-binds-to-the-wrong-r).

## Next

- [Your first walkthrough](first-walkthrough.md) — run the wizard end to end.
- [Troubleshooting](troubleshooting.md) — when `.rds` import misbehaves.
