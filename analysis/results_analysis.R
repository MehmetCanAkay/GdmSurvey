# =============================================================================
# GDM LLM Çalışması - İstatistik Analiz Scripti
#
# Bu script SQLite veritabanından verileri çekerek tüm istatistiksel analizleri
# gerçekleştirir: tanımlayıcı istatistikler, Friedman testi, post-hoc Wilcoxon,
# ICC, Fleiss kappa, Cronbach alfa ve karma etkili modeller.
# =============================================================================

# Gerekli paketler
required_packages <- c(
  "DBI", "RSQLite",    # Veritabanı bağlantısı
  "dplyr", "tidyr",    # Veri manipülasyonu
  "irr",               # ICC ve Fleiss kappa
  "psych",             # Cronbach alfa, ICC
  "lme4",              # Karma etkili modeller
  "ordinal",           # Ordinal karma modeller (clmm)
  "PMCMRplus",         # Post-hoc Friedman testleri
  "ggplot2",           # Görselleştirme
  "writexl"            # Excel çıktı
)

# Paketleri yükle (eksik olanları kur)
for (pkg in required_packages) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    install.packages(pkg, repos = "https://cran.r-project.org")
  }
  library(pkg, character.only = TRUE)
}

# =============================================================================
# 1. VERİTABANI BAĞLANTISI
# =============================================================================

db_path <- file.path(dirname(getwd()), "data", "study.db")
if (!file.exists(db_path)) {
  db_path <- "data/study.db"  # Alternatif yol
}

con <- dbConnect(RSQLite::SQLite(), db_path)

# Tabloları oku
responses_df <- dbGetQuery(con, "
  SELECT r.*, q.axis, q.type as question_type, m.provider, m.model_string
  FROM responses r
  JOIN questions q ON r.question_id = q.question_id
  JOIN models m ON r.model_id = m.model_id
")

scores_df <- dbGetQuery(con, "
  SELECT s.*, r.blind_code, r.question_id, r.model_id,
         q.axis, m.provider
  FROM scores s
  JOIN responses r ON s.response_id = r.response_id
  JOIN questions q ON r.question_id = q.question_id
  JOIN models m ON r.model_id = m.model_id
")

readability_df <- dbGetQuery(con, "
  SELECT rd.*, r.model_id, r.question_id, q.axis, m.provider
  FROM readability rd
  JOIN responses r ON rd.response_id = r.response_id
  JOIN questions q ON r.question_id = q.question_id
  JOIN models m ON r.model_id = m.model_id
")

dbDisconnect(con)

cat("Veri yüklendi.\n")
cat(sprintf("  Yanıt sayısı: %d\n", nrow(responses_df)))
cat(sprintf("  Puanlama sayısı: %d\n", nrow(scores_df)))
cat(sprintf("  Okunabilirlik kaydı: %d\n", nrow(readability_df)))

# =============================================================================
# 2. TANIMLAYICI İSTATİSTİKLER
# =============================================================================

cat("\n=== TANIMLAYICI İSTATİSTİKLER ===\n")

# Model bazında GQS
gqs_summary <- scores_df %>%
  group_by(provider) %>%
  summarise(
    n = n(),
    median_gqs = median(gqs, na.rm = TRUE),
    iqr_gqs = IQR(gqs, na.rm = TRUE),
    mean_gqs = mean(gqs, na.rm = TRUE),
    sd_gqs = sd(gqs, na.rm = TRUE),
    .groups = "drop"
  )

cat("\nGQS Puanları (Model bazında):\n")
print(gqs_summary)

# Model bazında DISCERN
discern_summary <- scores_df %>%
  group_by(provider) %>%
  summarise(
    median_discern = median(discern_total, na.rm = TRUE),
    iqr_discern = IQR(discern_total, na.rm = TRUE),
    .groups = "drop"
  )

cat("\nDISCERN Puanları:\n")
print(discern_summary)

# Model bazında CAS
cas_summary <- scores_df %>%
  group_by(provider) %>%
  summarise(
    median_cas = median(cas_total, na.rm = TRUE),
    iqr_cas = IQR(cas_total, na.rm = TRUE),
    .groups = "drop"
  )

cat("\nCAS Puanları:\n")
print(cas_summary)

# Okunabilirlik
readability_summary <- readability_df %>%
  group_by(provider) %>%
  summarise(
    mean_atesman = mean(atesman_score, na.rm = TRUE),
    sd_atesman = sd(atesman_score, na.rm = TRUE),
    mean_bezirci = mean(bezirci_yilmaz_grade, na.rm = TRUE),
    sd_bezirci = sd(bezirci_yilmaz_grade, na.rm = TRUE),
    mean_words = mean(word_count, na.rm = TRUE),
    .groups = "drop"
  )

cat("\nOkunabilirlik Skorları:\n")
print(readability_summary)

# Güvenlik endişesi oranı
safety_summary <- scores_df %>%
  group_by(provider) %>%
  summarise(
    total = n(),
    safety_concerns = sum(safety_issue == 1, na.rm = TRUE),
    safety_rate = safety_concerns / total * 100,
    .groups = "drop"
  )

cat("\nGüvenlik Endişesi Oranları:\n")
print(safety_summary)

# =============================================================================
# 3. FRIEDMAN TESTİ
# =============================================================================

cat("\n=== FRIEDMAN TESTİ ===\n")

# GQS için Friedman (her soru bir blok, modeller karşılaştırılır)
gqs_wide <- scores_df %>%
  group_by(question_id, provider) %>%
  summarise(mean_gqs = mean(gqs, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = provider, values_from = mean_gqs) %>%
  na.omit()

if (nrow(gqs_wide) >= 3) {
  gqs_matrix <- as.matrix(gqs_wide[, -1])
  friedman_gqs <- friedman.test(gqs_matrix)
  cat("\nGQS Friedman Testi:\n")
  print(friedman_gqs)
}

# DISCERN için Friedman
discern_wide <- scores_df %>%
  group_by(question_id, provider) %>%
  summarise(mean_discern = mean(discern_total, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = provider, values_from = mean_discern) %>%
  na.omit()

if (nrow(discern_wide) >= 3) {
  discern_matrix <- as.matrix(discern_wide[, -1])
  friedman_discern <- friedman.test(discern_matrix)
  cat("\nDISCERN Friedman Testi:\n")
  print(friedman_discern)
}

# CAS için Friedman
cas_wide <- scores_df %>%
  group_by(question_id, provider) %>%
  summarise(mean_cas = mean(cas_total, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = provider, values_from = mean_cas) %>%
  na.omit()

if (nrow(cas_wide) >= 3) {
  cas_matrix <- as.matrix(cas_wide[, -1])
  friedman_cas <- friedman.test(cas_matrix)
  cat("\nCAS Friedman Testi:\n")
  print(friedman_cas)
}

# =============================================================================
# 4. POST-HOC WILCOXON + BONFERRONI
# =============================================================================

cat("\n=== POST-HOC KARŞILAŞTIRMALAR (Wilcoxon + Bonferroni) ===\n")

providers <- unique(scores_df$provider)
n_comparisons <- choose(length(providers), 2)

# GQS ikili karşılaştırmalar
cat("\nGQS İkili Karşılaştırmalar:\n")
for (i in 1:(length(providers) - 1)) {
  for (j in (i + 1):length(providers)) {
    group1 <- scores_df$gqs[scores_df$provider == providers[i]]
    group2 <- scores_df$gqs[scores_df$provider == providers[j]]

    if (length(group1) > 0 && length(group2) > 0) {
      test <- wilcox.test(group1, group2)
      p_adj <- min(test$p.value * n_comparisons, 1)
      cat(sprintf("  %s vs %s: W=%.1f, p=%.4f, p_adj=%.4f\n",
                  providers[i], providers[j], test$statistic, test$p.value, p_adj))
    }
  }
}

# =============================================================================
# 5. KARMA ETKİLİ MODEL
# =============================================================================

cat("\n=== KARMA ETKİLİ MODELLER ===\n")

# GQS için karma model: model sabit etki, soru ve değerlendirici rastgele etki
if (nrow(scores_df) > 10) {
  scores_df$provider_factor <- as.factor(scores_df$provider)
  scores_df$question_factor <- as.factor(scores_df$question_id)
  scores_df$evaluator_factor <- as.factor(scores_df$evaluator_id)

  tryCatch({
    model_gqs <- lmer(
      gqs ~ provider_factor + (1 | question_factor) + (1 | evaluator_factor),
      data = scores_df
    )
    cat("\nGQS Karma Model:\n")
    print(summary(model_gqs))
  }, error = function(e) {
    cat(sprintf("  Karma model hatası: %s\n", e$message))
  })
}

# =============================================================================
# 6. ICC (SINIF İÇİ KORELASYON)
# =============================================================================

cat("\n=== ICC (Sınıf İçi Korelasyon) ===\n")

# GQS için ICC - değerlendiriciler arası tutarlılık
icc_data <- scores_df %>%
  select(response_id, evaluator_id, gqs) %>%
  pivot_wider(names_from = evaluator_id, values_from = gqs) %>%
  select(-response_id) %>%
  na.omit()

if (ncol(icc_data) >= 2 && nrow(icc_data) >= 3) {
  icc_result <- ICC(icc_data)
  cat("\nGQS ICC Sonuçları:\n")
  print(icc_result$results)
}

# =============================================================================
# 7. FLEISS KAPPA
# =============================================================================

cat("\n=== FLEISS KAPPA ===\n")

# GQS kategorileri için Fleiss kappa
kappa_data <- scores_df %>%
  select(response_id, evaluator_id, gqs) %>%
  pivot_wider(names_from = evaluator_id, values_from = gqs) %>%
  select(-response_id) %>%
  na.omit()

if (ncol(kappa_data) >= 2 && nrow(kappa_data) >= 3) {
  kappa_result <- kappam.fleiss(as.matrix(kappa_data))
  cat("\nGQS Fleiss Kappa:\n")
  print(kappa_result)
}

# =============================================================================
# 8. CRONBACH ALFA
# =============================================================================

cat("\n=== CRONBACH ALFA ===\n")

# CAS maddeleri için iç tutarlılık
cas_items <- scores_df %>%
  select(cas_food, cas_religion, cas_health_system, cas_local, cas_cultural) %>%
  na.omit()

if (nrow(cas_items) >= 5) {
  alpha_result <- psych::alpha(cas_items)
  cat("\nCAS Cronbach Alfa:\n")
  cat(sprintf("  Raw alpha: %.3f\n", alpha_result$total$raw_alpha))
  cat(sprintf("  Std alpha: %.3f\n", alpha_result$total$std.alpha))
}

# =============================================================================
# 9. EKSEN BAZINDA ANALİZ
# =============================================================================

cat("\n=== EKSEN BAZINDA ANALİZ ===\n")

axes <- unique(scores_df$axis)
for (ax in axes) {
  cat(sprintf("\n--- Eksen: %s ---\n", ax))
  subset <- scores_df %>% filter(axis == ax)

  cat(sprintf("  n = %d puanlama\n", nrow(subset)))
  cat(sprintf("  GQS medyan: %.1f (IQR: %.1f)\n",
              median(subset$gqs, na.rm = TRUE),
              IQR(subset$gqs, na.rm = TRUE)))
  cat(sprintf("  CAS medyan: %.1f (IQR: %.1f)\n",
              median(subset$cas_total, na.rm = TRUE),
              IQR(subset$cas_total, na.rm = TRUE)))
}

# =============================================================================
# 10. SONUÇLARI DIŞA AKTAR
# =============================================================================

cat("\n=== SONUÇLARI DIŞA AKTARMA ===\n")

output_dir <- file.path(dirname(getwd()), "analysis", "output")
if (!dir.exists(output_dir)) {
  dir.create(output_dir, recursive = TRUE)
}

# Özet tabloları Excel'e yaz
tryCatch({
  writexl::write_xlsx(
    list(
      GQS_Summary = gqs_summary,
      DISCERN_Summary = discern_summary,
      CAS_Summary = cas_summary,
      Readability = readability_summary,
      Safety = safety_summary
    ),
    path = file.path(output_dir, "summary_tables.xlsx")
  )
  cat("Özet tablolar kaydedildi: analysis/output/summary_tables.xlsx\n")
}, error = function(e) {
  cat(sprintf("Excel kayıt hatası: %s\n", e$message))
})

cat("\n=== ANALİZ TAMAMLANDI ===\n")
