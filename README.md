# Alpha Lab

Alpha Lab is a lightweight A-share historical event-study system. It screens historical stock observations by conditions such as turnover rate and popularity rank, then measures forward performance over configurable trading-day horizons.

The first MVP focuses on a small, auditable core:

- import daily market bars and historical popularity data;
- filter by turnover-rate and popularity-rank ranges;
- calculate forward 1/3/5/10/20 trading-day returns;
- report positive-return rate, average return, median return and sample size;
- expose the analysis through a simple API and web UI.

> This repository is under active development. Data-source adapters are intentionally separated from the analysis engine so HiThink Financial-API and other sources can be added without changing statistical logic.
