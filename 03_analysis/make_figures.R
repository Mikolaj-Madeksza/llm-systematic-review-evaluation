args <- commandArgs(trailingOnly = FALSE)
script <- sub("^--file=", "", args[grepl("^--file=", args)])
script <- gsub("~+~", " ", script, fixed = TRUE)
A <- dirname(normalizePath(script))
lib <- Sys.getenv("LLM_SLR_R_LIBRARY", "")
if (nzchar(lib)) .libPaths(c(lib, .libPaths()))
library(ggplot2)
library(patchwork)
O <- file.path(A, "results/current")
F <- file.path(O, "figures")
font <- "Arial"
dir.create(F, recursive = TRUE, showWarnings = FALSE)
stopifnot(font %in% systemfonts::system_fonts()$family)
base <- theme_minimal(base_family = font, base_size = 10) + theme(
  text = element_text(
    family = font,
    colour = "#202020"
  ), plot.title = element_text(face = "bold", size = 11), panel.grid.minor = element_blank(),
  panel.grid.major.y = element_blank(), axis.title.y = element_blank(), legend.title = element_blank(),
  legend.position = "bottom", plot.margin = margin(7, 12, 7, 5)
)
theme_set(base)
forest <- function(d, ref, xlab) {
  ggplot(d, aes(estimate, label)) +
    geom_vline(
      xintercept = ref, linetype = 2, colour = "#888888",
      linewidth = 0.35
    ) +
    geom_errorbar(aes(xmin = ci_low, xmax = ci_high),
      orientation = "y",
      width = 0.12, linewidth = 0.5, colour = "#344A58"
    ) +
    geom_point(size = 2.2, colour = "#344A58") +
    labs(x = xlab)
}
saveplot <- function(p, n, w, h) {
  previous <- options(warn = 2)
  on.exit(options(previous))
  ggsave(file.path(F, paste0(n, ".png")), p,
    width = w, height = h, dpi = 300, device = ragg::agg_png,
    bg = "white"
  )
  if (Sys.info()[["sysname"]] == "Darwin") {
    quartz(
      file = file.path(F, paste0(n, ".pdf")), type = "pdf",
      width = w, height = h, family = font
    )
  } else {
    stopifnot(capabilities("cairo"))
    cairo_pdf(
      file = file.path(F, paste0(n, ".pdf")),
      width = w, height = h, family = font
    )
  }
  print(p)
  invisible(dev.off())
}
a <- read.csv(file.path(O, "model_contrasts.csv"))
a <- subset(a, scope %in% c("data_primary", "rob_primary") & version == "original" & clustering ==
  "report")
a[, c("estimate", "ci_low", "ci_high")] <- a[, c("estimate", "ci_low", "ci_high")] * 100
a$label <- factor(ifelse(a$scope == "data_primary", "Data extraction:\nall eligible fields",
  "RoB: judgments and\nexplanations"
), levels = c("RoB: judgments and\nexplanations", "Data extraction:\nall eligible fields"))
pA <- forest(a, 0, "Difference in accuracy: GPT − Claude (pp)") + labs(title = "A  Accuracy before human verification") +
  scale_x_continuous(limits = c(-1, 10), breaks = c(0, 2, 4, 6, 8, 10))
t <- read.csv(file.path(O, "uncertainty_flag_performance.csv"))
t <- subset(t, scope %in% c("data_emitted_primary", "rob_emitted_primary") & clustering ==
  "report" & flag_definition == "any_U1_U2")
t$model <- ifelse(t$model == "gpt", "GPT", "Claude")
t$label <- factor(paste(ifelse(t$scope == "data_emitted_primary", "Data extraction", "RoB"),
  t$model,
  sep = " — "
), levels = c(
  "RoB — Claude", "RoB — GPT", "Data extraction — Claude",
  "Data extraction — GPT"
))
bplot <- function(d) {
  ggplot(d, aes(estimate, label, colour = model, shape = model)) +
    geom_errorbar(aes(
      xmin = ci_low,
      xmax = ci_high
    ), orientation = "y", width = 0.13, linewidth = 0.5) +
    geom_point(size = 2.2) +
    scale_colour_manual(values = c(GPT = "#245A81", Claude = "#B36B26")) +
    scale_shape_manual(values = c(
      GPT = 16,
      Claude = 17
    )) +
    theme(legend.position = "none")
}
s <- subset(t, metric == "sensitivity")
s[, c("estimate", "ci_low", "ci_high")] <- s[, c("estimate", "ci_low", "ci_high")] * 100
pB1 <- bplot(s) + scale_x_continuous(limits = c(0, 100), breaks = seq(0, 100, 25)) + labs(
  title = "B  How well uncertainty flags identified errors",
  x = "Sensitivity of uncertainty flags (%)"
)
pB2 <- bplot(subset(t, metric == "relative_enrichment")) + geom_vline(
  xintercept = 1, linetype = 2,
  colour = "#888888", linewidth = 0.35
) + scale_x_continuous(limits = c(0, 12), breaks = seq(
  0,
  12, 3
)) + labs(title = " ", x = "Error-rate ratio (flagged / unflagged)")
tm <- subset(read.csv(file.path(O, "timing_effects.csv")), specification == "primary")
tm$label <- factor(ifelse(tm$task == "data", "Data extraction", "RoB"), levels = c(
  "RoB",
  "Data extraction"
))
pC1 <- forest(tm, 1, "Adjusted verification time ratio (shown / hidden)\nBelow 1: less time with flags shown") +
  labs(title = "C  Effects of showing uncertainty flags") + scale_x_continuous(limits = c(
    0.65,
    1.35
  ), breaks = c(0.7, 0.85, 1, 1.15, 1.3))
n <- subset(read.csv(file.path(O, "net_verification_change_contrasts.csv")), model == "pooled" &
  clustering == "report" & scope %in% c("data_primary", "rob_primary"))
n$label <- factor(ifelse(n$scope == "data_primary", "Data extraction", "RoB"), levels = c(
  "RoB",
  "Data extraction"
))
n[, c("estimate", "ci_low", "ci_high")] <- n[, c("estimate", "ci_low", "ci_high")] * 100
pC2 <- forest(n, 0, "Difference in error-rate change (shown − hidden, pp)\nPositive: less favorable change with flags shown") +
  labs(title = " ") + scale_x_continuous(limits = c(-0.8, 3), breaks = c(0, 1, 2, 3))
pC1 <- pC1 + theme(axis.title.x = element_text(size = 8))
pC2 <- pC2 + theme(axis.title.x = element_text(size = 8))
p <- pA / (pB1 + pB2) / (pC1 + pC2) + plot_layout(heights = c(1, 1.65, 1.35))
saveplot(p, "figure_1_summary", 7.2, 8.2)
s <- read.csv(file.path(O, "uncertainty_flag_performance.csv"))
s <- subset(s, scope %in% c("data_emitted_primary", "data_all_target_safety") & clustering ==
  "report" & metric %in% c("sensitivity", "npv"))
s$model <- factor(ifelse(s$model == "gpt", "GPT", "Claude"), levels = c("Claude", "GPT"))
s$set <- factor(ifelse(s$scope == "data_emitted_primary", "Emitted outputs only", "All eligible targets"),
  levels = c("Emitted outputs only", "All eligible targets")
)
omit <- function(key, title, lims, breaks) {
  d <- s[s$metric == key, ]
  ggplot(d, aes(estimate * 100, model, shape = set, colour = set)) +
    geom_errorbar(
      aes(xmin = ci_low *
        100, xmax = ci_high * 100),
      orientation = "y", position = position_dodge(width = 0.4),
      width = 0.13, linewidth = 0.5
    ) +
    geom_point(
      position = position_dodge(width = 0.4),
      size = 2.3
    ) +
    scale_shape_manual(values = c(16, 17)) +
    scale_colour_manual(values = c(
      "#245A81",
      "#B36B26"
    )) +
    scale_x_continuous(limits = lims, breaks = breaks) +
    labs(
      title = title,
      x = paste0(title, " (%)")
    )
}
pS <- omit("sensitivity", "Sensitivity", c(0, 75), seq(0, 75, 15)) + omit(
  "npv", "Negative predictive value",
  c(60, 100), seq(60, 100, 10)
) + plot_layout(guides = "collect") & theme(legend.position = "bottom")
saveplot(pS, "figure_S1_omission_sensitivity", 7.2, 3.2)
