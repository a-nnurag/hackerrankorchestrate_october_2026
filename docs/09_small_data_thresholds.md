# 09. Tuning thresholds with very little labelled data

Web research (2026-10-25) and how it applies. The sources are papers, a working paper and library documentation; none
addresses this task, and several results were seen only as abstracts or summaries, so they give direction, not constants.

## What the sources say

- **Report intervals that suit small samples.** Wilson intervals cover better than Wald or normal approximations when the
  test set has about 100 or fewer items ([arXiv 2309.14621](https://arxiv.org/pdf/2309.14621),
  [arXiv 2503.01747](https://arxiv.org/pdf/2503.01747)); Jeffreys and Clopper-Pearson style intervals behave well when the
  rate is near 0 or 1, and the usual maximum-likelihood interval is discouraged there
  ([beta-binomial analysis](https://arxiv.org/pdf/2008.13619), [Jeffreys interval](https://metricgate.com/calculator/jeffreys-interval)).
  A practical rule that follows: use the lower bound of the interval on precision and pick the lowest threshold whose
  lower bound still meets the target. A library for fixed thresholds on small calibration sets uses a beta-binomial
  bound that also accounts for test-sampling noise ([ssbc](https://ssbc.readthedocs.io/en/latest/_autosummary/ssbc.bounds.html)).
- **Control the risk of what you accept (selective prediction).** Selective conformal risk control chooses a selection
  threshold on calibration data and bounds the risk on the accepted items; a newer paper certifies the risk of a threshold
  chosen adaptively from a grid on the same calibration data with Clopper-Pearson and empirical-Bernstein bounds
  ([Selective Conformal Risk Control](https://arxiv.org/pdf/2512.12844), [arXiv 2606.08517](https://papers.cool/arxiv/2606.08517)).
  Tuning and certifying on the same few cases without such a correction is optimistic.
- **Nested cross-validation** gives a low-bias estimate of the whole tuning procedure when a separate test set is
  impossible, at higher cost ([Raschka review](https://arxiv.org/pdf/1811.12808),
  [small-data study](https://arxiv.org/pdf/2208.10784)); sources disagree on how to pick the final setting (majority of the
  inner choices, or one more cross-validation). Nothing found settles a one-standard-error or plateau rule for tiny sets.
- **Record linkage without labels.** Unsupervised EM can estimate m and u probabilities, but a Census Bureau paper argues
  that false-match and false-non-match rates are likely impossible to estimate without training data, and others warn
  that EM estimates are often poor when comparisons are dependent ([Census working paper](https://www.census.gov/content/dam/Census/library/working-papers/2007/adrm/rrs2007-05.pdf),
  [Statistics Canada](https://www150.statcan.gc.ca/n1/en/catalogue/11-522-X202200100001)). Use such tables as ordering
  evidence, not as error rates; the reclin2 documentation bounds extreme values for stability
  ([problink_em](https://rdrr.io/pkg/reclin2/man/problink_em.html)).

## What it means here

1. Judge a link type by the lower end of an exact interval, not by the observed rate (done in `threshold_uncertainty.py`):
   exact identifiers 83 of 84, lower bound 0.94; unique-anchor activity clusters 17 of 17, lower bound 0.80; the second-offset
   resolver 3 of 3, lower bound 0.29: the samples cannot vouch for it.
2. Make labels from the data. Exact-linked accounts are true labels for the resolver once the link is hidden (cross-fitted):
   50 picks, 0 wrong, 24 abstentions, exact interval [0.929, 1.000] on those cases.
3. Treat agreement between two implementations as a weak pseudo-label with its own interval, and separate "contradicted"
   from "silent".
4. Keep learned tables as tie-breakers with a margin and a review flag, as the unsupervised-estimation warnings advise.
5. Do not over-tune: the leave-one-case-out and bootstrap already in `robustness.py` are the appropriate check for the
   few remaining settings (min_link 0.45, the anchor window), and they are chosen consistently in all folds.

Results are in `code/evaluation/evaluation_report.md` section 18.
