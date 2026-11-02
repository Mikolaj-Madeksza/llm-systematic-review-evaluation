args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
script <- gsub("~+~", " ", script, fixed = TRUE)
A <- dirname(normalizePath(script))
O <- file.path(A, "results/current")
lib <- Sys.getenv("LLM_SLR_R_LIBRARY", "")
if (nzchar(lib)) .libPaths(c(lib, .libPaths()))
suppressPackageStartupMessages(library(clubSandwich))
s <- read.csv(file.path(dirname(A), "02_data", "sessions.csv"), check.names = FALSE)
cl <- read.csv(file.path(dirname(A), "02_data", "study_clusters.csv"))
s$known_cluster <- cl$known_trial_cluster_id[match(s$study_id, cl$study_id)]
s$explicit_flag_visibility <- factor(s$uncertainty_visibility, levels = c("hidden", "visible"))
s$model <- factor(s$model, levels = c("claude", "gpt"))
s$reviewer <- factor(s$reviewer, levels = c("BJ", "MK"))
stopifnot(nrow(s) == 384, !anyDuplicated(s$session_id), all(s$time_s > 0))
results <- list()
diagnostics <- list()
models <- list()
for (task in c("data", "rob")) {
  x <- s[s$task == task, ]
  x$study_id <- factor(x$study_id)
  x$order_centered <- x$review_order - mean(x$review_order)
  x$log_rows <- log(x$original_row_burden) - mean(log(x$original_row_burden))
  x$log_fields <- log(x$original_nonblank_field_burden_excluding_uncertainty) - mean(log(x$original_nonblank_field_burden_excluding_uncertainty))
  for (spec in c(
    "primary", "omit_burden", "field_burden", "raw_seconds", "known_companion",
    "model_interaction"
  )) {
    rhs <- "study_id + model + reviewer + explicit_flag_visibility + order_centered"
    if (task == "data" && spec != "omit_burden" && spec != "field_burden") {
      rhs <- paste(rhs, "+ log_rows")
    }
    if (spec == "field_burden") {
      rhs <- paste(rhs, "+ log_fields")
    }
    if (spec == "model_interaction") {
      rhs <- paste(rhs, "+ model:explicit_flag_visibility")
    }
    response <- if (spec == "raw_seconds") {
      "time_s"
    } else {
      "log(time_s)"
    }
    form <- as.formula(paste(response, "~", rhs))
    mm <- model.matrix(form, x)
    dropped <- ""
    if (qr(mm)$rank < ncol(mm) && spec == "field_burden") {
      rhs <- sub(" \\+ log_fields", "", rhs)
      dropped <- "Field burden absorbed by report effects"
      form <- as.formula(paste(response, "~", rhs))
      mm <- model.matrix(form, x)
    }
    stopifnot(qr(mm)$rank == ncol(mm))
    fit <- lm(form, x)
    cluster <- if (spec == "known_companion") {
      x$known_cluster
    } else {
      x$study_id
    }
    vc <- clubSandwich::vcovCR(fit, cluster = cluster, type = "CR2")
    terms <- if (spec == "model_interaction") {
      c("explicit_flag_visibilityvisible", "modelgpt:explicit_flag_visibilityvisible")
    } else {
      "explicit_flag_visibilityvisible"
    }
    ci <- clubSandwich::conf_int(fit, vcov = vc, test = "Satterthwaite", coefs = terms)
    for (i in seq_len(nrow(ci))) {
      row <- ci[i, ]
      israw <- spec == "raw_seconds"
      results[[length(results) + 1]] <- data.frame(
        task = task, specification = spec,
        term = as.character(row$Coef), estimate = if (israw) {
          row$beta
        } else {
          exp(row$beta)
        }, ci_low = if (israw) {
          row$CI_L
        } else {
          exp(row$CI_L)
        }, ci_high = if (israw) {
          row$CI_U
        } else {
          exp(row$CI_U)
        }, scale = if (israw) {
          "seconds_difference"
        } else if (grepl(":", row$Coef)) {
          "ratio_of_visibility_ratios"
        } else {
          "visible_hidden_geometric_mean_ratio"
        }, log_or_raw_coefficient = row$beta,
        SE_CR2 = row$SE, df_Satterthwaite = row$df, n_sessions = nrow(x), n_clusters = length(unique(cluster)),
        dropped_collinear_term = dropped
      )
    }
    models[[paste(task, spec, sep = "_")]] <- list(fit = fit, vcov_CR2 = vc, cluster = cluster)
    diagnostics[[length(diagnostics) + 1]] <- data.frame(
      task = task, specification = spec,
      rank = fit$rank, columns = ncol(mm), residual_df = df.residual(fit), max_abs_standardized_residual = max(abs(rstandard(fit))),
      min_seconds = min(x$time_s), max_seconds = max(x$time_s), formula = paste(deparse(form),
        collapse = " "
      )
    )
  }
}
write.csv(do.call(rbind, results), file.path(O, "timing_effects.csv"), row.names = FALSE)
write.csv(do.call(rbind, diagnostics), file.path(O, "timing_model_diagnostics.csv"), row.names = FALSE)
saveRDS(models, file.path(O, "timing_fits.rds"))
descriptive <- list()
for (task in c("data", "rob")) {
  for (v in c("hidden", "visible")) {
    x <- s[s$task == task & s$explicit_flag_visibility == v, ]
    for (unit in c("seconds", "seconds_per_original_nonblank_field")) {
      z <- if (unit == "seconds") {
        x$time_s
      } else {
        x$time_s / x$original_nonblank_field_burden_excluding_uncertainty
      }
      descriptive[[length(descriptive) + 1]] <- data.frame(
        task = task, explicit_flag_visibility = v,
        unit = unit, n = length(z), median = median(z), q1 = unname(quantile(z, 0.25)),
        q3 = unname(quantile(z, 0.75)), mean = mean(z), sd = sd(z), min = min(z), max = max(z)
      )
    }
  }
}
write.csv(do.call(rbind, descriptive), file.path(O, "timing_descriptive.csv"), row.names = FALSE)
capture.output(sessionInfo(), file = file.path(O, "R_session_info.txt"))
writeLines(c(
  "CR2 and Satterthwaite confidence intervals implemented by clubSandwich.", "https://jepusto.github.io/clubSandwich/reference/conf_int.html",
  "https://jepusto.github.io/clubSandwich/reference/coef_test.html"
), file.path(O, "statistical_software_sources.txt"))
cat("Timing primary and sensitivity models completed.\n")
