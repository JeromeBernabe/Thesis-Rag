==========================================================================================
DESCRIPTIVE STATISTICS PER SYSTEM
==========================================================================================
system_id           metric  count     mean      std      min      max
        A     faithfulness     50 0.598444 0.436903 0.000000 1.000000
        A answer_relevancy     50 0.730433 0.206433 0.306383 0.988914
        A   context_recall     49 0.281020 0.377063 0.000000 1.000000
        B     faithfulness     50 0.651000 0.415480 0.000000 1.000000
        B answer_relevancy     50 0.763853 0.170726 0.341830 0.991289
        B   context_recall     49 0.233248 0.326174 0.000000 1.000000

==========================================================================================
STATISTICAL TESTS (System B - System A), alpha = 0.05
==========================================================================================
          metric  n_pairs   mean_a   mean_b  mean_difference  cohens_d  ci_95_low  ci_95_high  t_statistic  p_two_tailed  p_one_tailed  sig_two_tailed  sig_one_tailed  wilcoxon_stat  wilcoxon_p_two  wilcoxon_p_one  wilcoxon_sig_one
    faithfulness       50 0.598444 0.651000         0.052556    0.1034    -0.0918      0.1970      -0.7314      0.468028      0.765986           False           False          181.0        0.428221        0.214111             False
answer_relevancy       50 0.730433 0.763853         0.033420    0.1372    -0.0358      0.1027      -0.9700      0.336812      0.831594           False           False          479.0        0.501641        0.250820             False
  context_recall       49 0.281020 0.233248        -0.047771   -0.2176    -0.1108      0.0153       1.5232      0.134278      0.067139           False           False           21.5        0.169646        0.915177             False

Note: p_one_tailed tests H1: B > A (directional hypothesis).
      wilcoxon_* are non-parametric Wilcoxon signed-rank tests.
      CI 95% is for the mean difference (B - A).