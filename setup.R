args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
root <- dirname(normalizePath(gsub("~+~", " ", script, fixed = TRUE)))
if (!requireNamespace("renv", quietly = TRUE)) {
  install.packages("renv", repos = "https://cloud.r-project.org")
}
renv::restore(
  project = root,
  lockfile = file.path(root, "renv.lock"),
  library = file.path(root, "renv", "library"),
  prompt = FALSE
)
