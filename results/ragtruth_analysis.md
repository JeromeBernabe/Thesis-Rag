==========================================================================================
DESCRIPTIVE STATISTICS PER SYSTEM
==========================================================================================
system_id           metric  count     mean      std      min      max
        A     faithfulness     50 0.841874 0.258843 0.000000 1.000000
        A answer_relevancy     50 0.745227 0.105552 0.380758 0.916787
        A   context_recall     50 0.878168 0.275833 0.000000 1.000000
        B     faithfulness     50 0.839293 0.273303 0.000000 1.000000
        B answer_relevancy     50 0.719416 0.128124 0.397092 0.916787
        B   context_recall     50 0.892554 0.246461 0.000000 1.000000

==========================================================================================
STATISTICAL TESTS (System B - System A), alpha = 0.05
==========================================================================================
          metric  n_pairs   mean_a   mean_b  mean_difference  cohens_d  ci_95_low  ci_95_high  t_statistic  p_two_tailed  p_one_tailed  sig_two_tailed  sig_one_tailed  wilcoxon_stat  wilcoxon_p_two  wilcoxon_p_one  wilcoxon_sig_one
    faithfulness       50 0.841874 0.839293        -0.002581   -0.0074    -0.1020      0.0968       0.0522      0.958598      0.479299           False           False          232.0        0.753529        0.376764             False
answer_relevancy       50 0.745227 0.719416        -0.025811   -0.3109    -0.0494     -0.0022       2.1987      0.032649      0.016325            True            True          243.0        0.009134        0.995433             False
  context_recall       50 0.878168 0.892554         0.014387    0.0947    -0.0288      0.0576      -0.6695      0.506326      0.746837           False           False            7.0        0.892738        0.446369             False

Note: p_one_tailed tests H1: B > A (directional hypothesis).
      wilcoxon_* are non-parametric Wilcoxon signed-rank tests.
      CI 95% is for the mean difference (B - A).