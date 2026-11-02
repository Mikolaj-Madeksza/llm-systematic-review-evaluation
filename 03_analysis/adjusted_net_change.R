args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
script <- gsub("~+~", " ", script, fixed = TRUE)
A <- dirname(normalizePath(script))
lib <- Sys.getenv("LLM_SLR_R_LIBRARY", "")
if (nzchar(lib)) .libPaths(c(lib, .libPaths()))
suppressPackageStartupMessages(library(clubSandwich))
s <- read.csv(file.path(A, "results/current/net_change_sessions.csv"))
out <- list()
for (task in c("data", "rob")) {
  x <- s[s$task == task, ]
  x$study_id <- factor(x$study_id)
  x$model <- factor(x$model)
  x$reviewer <- factor(x$reviewer)
  x$visibility <- factor(x$explicit_flag_visibility, levels = c("hidden", "visible"))
  x$order <- x$review_order - mean(x$review_order)
  form <- delta ~ study_id + model + reviewer + visibility + order
  mm <- model.matrix(form, x)
  stopifnot(qr(mm)$rank == ncol(mm))
  fit <- lm(form, data = x, weights = n)
  v <- clubSandwich::vcovCR(fit, cluster = x$study_id, type = "CR2", inverse_var = FALSE)
  ci <- clubSandwich::conf_int(fit, vcov = v, test = "Satterthwaite", coefs = "visibilityvisible")
  out[[task]] <- data.frame(
    task = task, estimate = ci$beta, ci_low = ci$CI_L, ci_high = ci$CI_U,
    df = ci$df, n_sessions = nrow(x), n_fields = sum(x$n)
  )
}
write.csv(do.call(rbind, out), file.path(A, "results/current/adjusted_net_change.csv"), row.names = FALSE)
