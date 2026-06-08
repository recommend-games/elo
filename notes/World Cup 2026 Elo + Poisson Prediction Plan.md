This document describes a deliberately simple implementation plan for predicting the winner of the 2026 FIFA World Cup using established Elo ratings and a Poisson goal model.

The goal is to build a reproducible Monte Carlo simulator quickly, not to build a fully optimised football forecasting system.

## 1. Scope

### Main idea

Use this pipeline:

```text
Established World Football Elo ratings
    -> Elo-based expected result
    -> Poisson scoreline model
    -> group-stage simulation
    -> official knockout-path simulation
    -> title and round-reaching probabilities
```

### Included

- Use established public Elo ratings.
- Use a simple Poisson model for football scores.
- Simulate all group-stage matches as scorelines.
- Apply group ranking and best-third qualification rules.
- Simulate the round of 32 through the final.
- Run many Monte Carlo simulations.
- Produce CSV outputs and simple analysis tables.

### Excluded

- No custom Elo implementation.
- No player-level or squad-strength modelling.
- No injury modelling.
- No bookmaker odds integration for the first version.
- No backtesting for the first version.
- No card/conduct simulation.
- No detailed extra-time goal model.
- No Elo updates inside simulated tournaments.

## 2. Sources of truth

Use these sources or local snapshots derived from them:

1. World Football Elo Ratings
   - Main team-strength input.
   - Source: https://www.eloratings.net/
   - Mirror/snapshot-friendly table: https://www.international-football.net/elo-ratings-table

2. FIFA World Cup 2026 regulations
   - Source of tournament structure, group ranking, knockout rules, and third-place mapping.
   - Source: https://digitalhub.fifa.com/

3. FIFA World Cup 2026 official fixtures and groups
   - Source of groups, fixtures, venue countries, and knockout slots.
   - Source: https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026

Important: save local copies of all scraped or manually entered data. The simulation should not depend on live web access.

## 3. Expected repository structure

```text
world-cup-2026-elo/
  data/
    raw/
      elo_snapshot.csv
      fifa_teams_groups.csv
      fifa_fixtures.csv
      third_place_lookup.csv
    processed/
      teams.csv
      group_matches.csv
      knockout_slots.csv
  src/
    __init__.py
    config.py
    load_data.py
    poisson_model.py
    group_stage.py
    knockout.py
    simulate.py
    analyse.py
  outputs/
    team_probabilities.csv
    group_probabilities.csv
    simulation_summary.csv
  scripts/
    run_simulation.py
    make_tables.py
  tests/
    test_poisson_model.py
    test_group_stage.py
    test_third_place_lookup.py
    test_knockout.py
  README.md
```

Python 3.10+ is sufficient. Prefer Polars for tabular data and NumPy for simulation.

## 4. Input data files

### 4.1 `teams.csv`

One row per team.

Required columns:

```text
team_id              stable internal identifier, e.g. ARG, ESP, USA
team_name            display name
elo_name             name in the Elo source, if different
group                group letter, A-L
group_slot           group slot, e.g. A1, A2, ..., L4
elo                  Elo rating snapshot value
fifa_ranking         FIFA ranking, only used as rare tie-break fallback
is_host              boolean: true for Canada, Mexico, USA
host_country         Canada, Mexico, USA, or empty
```

Example:

```csv
team_id,team_name,elo_name,group,group_slot,elo,fifa_ranking,is_host,host_country
ARG,Argentina,Argentina,J,J1,2140,1,false,
USA,United States,United States,D,D1,1830,16,true,USA
```

The exact teams, groups, slots, ratings, and rankings must be filled from the frozen data snapshot.

### 4.2 `group_matches.csv`

One row per group-stage fixture.

Required columns:

```text
match_id
stage                 group
round_number          1, 2, or 3 within the group stage
group                 A-L
team_a_slot           e.g. A1
team_b_slot           e.g. A2
venue_country         Canada, Mexico, or USA
```

### 4.3 `knockout_slots.csv`

One row per fixed knockout fixture slot.

Required columns:

```text
match_id
stage                 R32, R16, QF, SF, FINAL
team_a_source         e.g. 1A, 2C, 3DEF, W101
team_b_source         e.g. 2B, 1F, W102
venue_country
winner_to             next match slot, empty for final
```

Notes:

- Sources like `1A` and `2C` are direct group placements.
- Sources involving third-placed teams depend on the FIFA third-place lookup table.
- Sources like `W101` refer to winners of earlier knockout matches.

### 4.4 `third_place_lookup.csv`

This table maps each combination of eight qualified third-placed groups to the corresponding round-of-32 slots.

Required columns:

```text
qualified_third_groups       string like ABCDEFGH, sorted alphabetically
slot_1                       e.g. 3C
slot_2                       e.g. 3E
slot_3                       e.g. 3A
...
```

Exact shape depends on how the bracket is represented, but it must be enough to deterministically place all qualified third-placed teams.

Acceptance criterion:

```text
number of rows == 495
```

There are C(12, 8) = 495 possible combinations of qualified third-placed teams.

## 5. Match model

### 5.1 Elo difference

For each match between team A and team B:

```text
d = elo_A - elo_B + host_adjustment_A - host_adjustment_B
```

Use this simple host adjustment:

```text
host_adjustment = 100 if the team is one of the hosts and the match is played in that team's own country
host_adjustment = 0 otherwise
```

Examples:

- USA playing in the USA: +100 for USA.
- Mexico playing in Mexico: +100 for Mexico.
- Canada playing in Canada: +100 for Canada.
- USA playing in Mexico: no host adjustment in the first version.
- Argentina vs Spain in the USA: no host adjustment.

### 5.2 Elo expected score

Convert Elo difference to expected score:

```text
s_A = 1 / (1 + 10 ** (-d / 400))
s_B = 1 - s_A
```

Interpretation:

```text
s_A = P(A wins) + 0.5 * P(draw)
```

This is not the same as pure win probability.

### 5.3 Poisson goal model

Use a fixed expected total number of goals:

```text
total_goals = 2.6
```

For each match, choose `lambda_A` and `lambda_B` such that:

```text
lambda_A + lambda_B = total_goals
PoissonExpectedScore(lambda_A, lambda_B) ~= s_A
```

where:

```text
PoissonExpectedScore(lambda_A, lambda_B)
    = P(goals_A > goals_B) + 0.5 * P(goals_A == goals_B)
```

Implementation:

1. Binary search over `lambda_A` in `[0, total_goals]`.
2. Set `lambda_B = total_goals - lambda_A`.
3. For each candidate pair, compute scoreline probabilities over a truncated grid.
4. Use the candidate where the expected score is closest to `s_A`.

Recommended truncation:

```text
max_goals = 10
```

This is enough for practical use. Probability mass above 10 goals is negligible for this model.

### 5.4 Caching

Cache lambdas by rounded Elo difference.

Example:

```text
rounded_d = round(d)
cache_key = rounded_d
```

This avoids running binary search millions of times.

## 6. Group-stage simulation

For each group match:

1. Compute Elo difference.
2. Convert to `lambda_A`, `lambda_B`.
3. Sample goals:

```text
goals_A ~ Poisson(lambda_A)
goals_B ~ Poisson(lambda_B)
```

4. Award points:

```text
win  -> 3 points
 draw -> 1 point each
 loss -> 0 points
```

Track per team:

```text
points
goals_for
goals_against
goal_difference
wins/draws/losses if useful
head-to-head results against group opponents
```

## 7. Group ranking rules

Implement these tie-breaks in this order:

1. Points.
2. Head-to-head points among tied teams.
3. Head-to-head goal difference among tied teams.
4. Head-to-head goals scored among tied teams.
5. Overall goal difference.
6. Overall goals scored.
7. FIFA ranking fallback.

The official regulations include team conduct score before the FIFA-ranking fallback. Do not simulate cards in the first version. Instead, go directly to FIFA ranking as the deterministic fallback.

Implementation note:

- Ties can involve two, three, or four teams.
- Apply the head-to-head criteria to the tied subset.
- If only some teams are separated by a criterion, resolve those positions and continue ranking the remaining tied teams recursively.
- For the first version, a simpler stable sort by all criteria over the tied subset is acceptable, as long as tests cover common cases.

## 8. Selecting teams for the knockout stage

From each group:

```text
rank 1 -> qualifies
rank 2 -> qualifies
rank 3 -> candidate for best-third qualification
rank 4 -> eliminated
```

Rank the twelve third-placed teams by:

1. Points.
2. Overall goal difference.
3. Overall goals scored.
4. FIFA ranking fallback.

Select the top eight.

Then use `third_place_lookup.csv` to map the eight qualified third-placed groups into the correct round-of-32 slots.

## 9. Knockout simulation

Use the same Poisson model for 90 minutes.

For each knockout match:

1. Compute Elo difference with host adjustment.
2. Convert to `lambda_A`, `lambda_B`.
3. Sample 90-minute goals.
4. If one team has more goals, that team advances.
5. If the score is tied, sample the advancing team from the Elo expected score:

```text
P(A advances after extra time / penalties) = s_A
P(B advances after extra time / penalties) = 1 - s_A
```

This intentionally avoids detailed extra-time and penalty modelling.

Track each team's furthest stage reached.

Recommended stage labels:

```text
GROUP_ELIMINATED
R32
R16
QF
SF
FINAL
WINNER
```

Interpretation:

- `R32` means eliminated in the round of 32.
- `R16` means eliminated in the round of 16.
- `QF` means eliminated in the quarter-finals.
- `SF` means eliminated in the semi-finals.
- `FINAL` means lost the final.
- `WINNER` means won the tournament.

## 10. Monte Carlo loop

Pseudocode:

```python
for sim_idx in range(n_simulations):
    group_results = simulate_group_stage(
        teams=teams,
        group_matches=group_matches,
        model=model,
        rng=rng,
    )

    group_rankings = rank_all_groups(group_results)

    qualifiers = select_qualifiers(
        group_rankings=group_rankings,
        third_place_lookup=third_place_lookup,
    )

    bracket = build_round_of_32(
        qualifiers=qualifiers,
        knockout_slots=knockout_slots,
    )

    tournament_result = simulate_knockout_stage(
        bracket=bracket,
        model=model,
        rng=rng,
    )

    accumulator.update(group_rankings, tournament_result)
```

Recommended simulation counts:

```text
10,000   for first debugging
100,000  for development checks
1,000,000 for final article outputs
```

Use a fixed random seed for reproducibility.

```text
seed = 20260611
```

## 11. Outputs

### 11.1 `team_probabilities.csv`

One row per team.

Columns:

```text
team_id
team_name
group
elo
fifa_ranking
p_group_winner
p_qualify_group
p_reach_r32
p_reach_r16
p_reach_qf
p_reach_sf
p_reach_final
p_winner
implied_decimal_odds
elo_rank
title_probability_rank
rank_difference
```

Notes:

- `p_reach_r32` should equal `p_qualify_group`.
- `implied_decimal_odds = 1 / p_winner`, unless `p_winner == 0`.
- `rank_difference = elo_rank - title_probability_rank`.
  - Positive values mean the team has a better title-probability rank than Elo rank.
  - Negative values mean the draw/path hurts them relative to Elo.

### 11.2 `group_probabilities.csv`

One row per team.

Columns:

```text
group
team_id
team_name
p_finish_1st
p_finish_2nd
p_finish_3rd
p_finish_4th
p_qualify
p_eliminated
```

### 11.3 `simulation_summary.csv`

Useful metadata:

```text
n_simulations
seed
elo_snapshot_date
total_goals
host_advantage
created_at
```

## 12. Suggested tables for the article

### Main title-probability table

```text
Team | Elo | Group | R32 | R16 | QF | SF | Final | Winner | Implied odds
```

Sort by `p_winner` descending.

### Group-by-group table

```text
Group | Team | 1st | 2nd | 3rd | Qualify | Eliminated
```

Sort by group and qualification probability.

### Draw benefit / path difficulty table

```text
Team | Elo rank | Title-probability rank | Difference
```

This is likely to be the most interesting narrative angle: which teams are helped or hurt by the draw.

## 13. Tests and acceptance criteria

### Data tests

- Exactly 48 teams.
- Exactly 12 groups.
- Exactly 4 teams per group.
- Every team has an Elo rating.
- Every team has a FIFA ranking fallback.
- Every group-stage fixture references valid group slots.
- Third-place lookup has exactly 495 rows.
- Every third-place lookup key contains exactly 8 distinct group letters from A-L.

### Poisson model tests

- For equal Elo ratings and no host advantage, `s_A` is approximately 0.5.
- For equal Elo ratings, `lambda_A` is approximately `lambda_B`.
- `lambda_A + lambda_B == total_goals`, within floating-point tolerance.
- Larger Elo difference produces larger `lambda_A` and smaller `lambda_B`.
- Implied Poisson expected score is close to Elo expected score.

### Group-stage tests

Create small synthetic groups with known results and verify:

- Points are calculated correctly.
- Goal difference is calculated correctly.
- Goals scored are calculated correctly.
- Two-team head-to-head tie-break works.
- Three-team tied mini-table works.
- FIFA-ranking fallback is deterministic.

### Qualification tests

- Top two from every group qualify.
- Exactly eight third-placed teams qualify.
- Exactly 32 teams enter the round of 32.
- The selected third-placed teams are correctly passed through the lookup table.

### Knockout tests

- Every knockout match produces exactly one winner.
- Exactly one tournament winner is produced per simulation.
- No eliminated team reappears in later rounds.
- Stage-reaching counts are internally consistent.

For final simulation output:

- Sum of `p_winner` over all teams is approximately 1.
- Sum of `p_reach_final` over all teams is approximately 2.
- Sum of `p_reach_sf` over all teams is approximately 4.
- Sum of `p_reach_qf` over all teams is approximately 8.
- Sum of `p_reach_r16` over all teams is approximately 16.
- Sum of `p_reach_r32` over all teams is approximately 32.

## 14. Implementation priorities

Build in this order:

1. Load and validate static data.
2. Implement Elo expected score.
3. Implement Poisson lambda fitting and score simulation.
4. Implement group-stage simulation.
5. Implement group ranking.
6. Implement best-third selection.
7. Implement third-place bracket mapping.
8. Implement knockout simulation.
9. Implement accumulator for probabilities.
10. Export CSV outputs.
11. Add article-ready tables.
12. Add tests around all tournament-structure edge cases.

## 15. Configuration defaults

Use these default values for the first version:

```text
n_simulations = 1_000_000
seed = 20260611
total_goals = 2.6
host_advantage = 100
max_goals = 10
elo_difference_cache_rounding = 1
```

Expose them in `src/config.py` or a small YAML/TOML config file.

## 16. Possible later extensions

Do not implement these for the first version, but keep the code flexible enough that they can be added later:

- Calibrate `total_goals` from recent international matches.
- Calibrate host advantage.
- Use different goal expectations for knockout and group-stage matches.
- Model extra time and penalties separately.
- Add bookmaker odds comparison.
- Add a simple custom Elo model as a robustness check.
- Add sensitivity analysis for `total_goals` and `host_advantage`.
- Add market-implied probabilities and de-vigging.
- Backtest on the 2014, 2018, and 2022 World Cups.

## 17. Summary for implementation agent

Implement a deterministic, reproducible World Cup simulator using established Elo ratings and a simple Poisson score model.

The most important correctness risks are:

1. Team/name mapping between FIFA data and Elo data.
2. Group tie-break logic.
3. Best-third qualification.
4. Third-place round-of-32 mapping.
5. Correct bracket progression.

Do not over-engineer the predictive model. The first version should be clear, testable, and article-ready.
