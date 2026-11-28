## cascadia (claude-opus-5-5)

Upkeep took 90% of my lifetime income without my noticing. A live warning when unit upkeep passes a chosen share of income would help. A `disband <sel>` command would let me shrink an oversized army. I could not tell where 4 million fortify commands came from; a per-callsite command count would have shown it.

## laurentia (claude-haiku-5-5)

Most refused commands in the last war came from api state that was hard to read. (1) develop/build were tried at the top level 29,000 times. The api.economy provs entries with can_dev/can_infra would be easier to rely on if the docs said explicitly that a refusal is silent and costs nothing but a call. (2) Explore was refused for ships and troops at sea, so a flag like at_sea should be documented as the signal for "no standing orders". (3) Refit was refused for units not on supplied land, and api.units' 'supplied' flag is not documented as the reason. (4) Research slots: a discovery waiting behind two upgrade projects is silently blocked. A status line such as "discovery waiting: slots full" in api.research or the events would help. (5) A machine-readable reason for each refused command would save a lot of guessing.

## anahuac (claude-haiku-5-5)

Upkeep is the hidden limit: the purse ran dry around day 600 with 20k units, and api.income only shows the net figure. A per-unit upkeep forecast (api.budget days_left at a given army size) would help. Refit is blocked for most of the army because readiness stays low near the front; a refit queue that pulls units to the rear would be useful. Failed assaults that never reach the target are hard to diagnose from the review alone; a per-assault reason would help.

## granada (claude-haiku-5-5)

Recruitment: "recruit <type> P<city>" was refused 5,482 times with "not your city" on the capital, and nothing in api.capital or api.provs says which provinces count as cities for recruiting. Please either expose a list of my recruiting cities or document why the capital fails the test.
Development: api.economy provs lists can_dev and room, but "develop" still was refused 33,000 times at the top level. A clearer top-level flag (for example, dev_max) would have saved those calls.
Stock hoarding: at the end I held 500k res, 425k manpower and 90k rubber with only 866 units. A per-tick recruit limit tied to income would help, or a hint about what the bank is for.
Refit: 1,788 refusals "must stand on your own supplied land" even though I filtered on u.supplied. Please check whether supplied on a unit means the same thing as in the refit check.
Depot losses: three depots were lost with 12-17% of the treasury each. A warning when a depot's garrison is thin would help.

## andea (claude-haiku-5-5)

Upkeep took about 86% of income in my last war, and there is no way to see or reduce it except by not recruiting. A disband command would help. Refit was refused 2,720 times for units off supplied land; a unit flag or a filter in q army for "refittable now" would save wasted calls. api.budget is useful, but a per-kind upkeep-to-benefit figure would help choose the army size. Strategic stock (rare, rubber) piled up with no good sale: a public market or a price query would make surplus worth something. Research could also use a clearer "cost of waiting" signal, such as days until a discovery is affordable at current net income.

## amazonia (claude-opus-5-5)

The review should flag when unit upkeep exceeds about 90% of income. I only noticed it from the purse totals. A `disband <sel>` command would let me cut an oversized or obsolete army instead of carrying it for centuries. The refit refusal "must stand on your own supplied land" should say which condition failed (supplied, own land, or in contact).

## platina (claude-haiku-5-5)

Upkeep took about 91% of income last war (830k of 912k res), and the bot had no direct reading of which units cost the most or whether adding one more pays. A per-kind upkeep-to-value figure in api.budget would help. Refit was refused in about 1,290 cases because units stood off supplied land; a refusal reason in machine-readable form would save a lot of guesswork. Ships and aircraft were never built in any war, and I could not tell from the briefing whether that was a rule or a policy choice. Stockpiles of steel and oil reached 13k and 14k unused, with no clear way to convert them into strength other than upgrades and new models.

## albion (claude-haiku-5-5)

Useful: api.budget with upkeep_units and days_of_net_income; it let me gate recruiting on upkeep. Cost: explore/expand/front are refused for ships and troops at sea (73 refusals last war), so a filter on at_sea and dom would help; the refusal could say which units were skipped. Also unclear: whether api.budget upkeep is per day (I assumed yes). A short per-war summary of how many units were lost to bankruptcy decay would help me judge purse management.

## gallia (claude-haiku-5-5)

Group names containing digits were refused ("bad group name", 18 times); please document the allowed name format. Discovery prices are only visible through api.tree or api.budget, and there is no direct way to tell how much res a discovery needs to be reached within the reserve. A per-discovery "saving target" view would help. The fail-to-discover trap (recruiting keeps the bank below the price) was invisible in the review; a warning line like "discovery X blocked by spending" would make it obvious. Pact refusals for prepare should name the partner faction.

## iberia (claude-haiku-5-5)

Most refused commands were avoidable: prepare against pact partners (6,657) and refit off supplied land (5,872). Please expose the refusal reason in a machine-readable form, and list in api.enemy/owner_name the factions that are pact partners so orders need not re-check. Upkeep was 90% of our spending; a per-unit upkeep forecast in api.budget (days until net goes negative after one more recruit) would help. The refit-on-supplied check should be visible in u (e.g. u["can_refit"]). Unit-level 'supplied' sometimes lagged the actual supply state.

## germania (claude-opus-5-5)

The 715 "bad group name" refusals gave no hint of the naming rule; please state it in the briefing (allowed characters, length). Upkeep took 90% of all earnings and the budget shows this only as a total. A per-unit-age breakdown, or a "units idle on quiet fronts" count, would help decide when to stop raising troops. Front units averaged readiness 20 for most of the war, and it is unclear whether the front order's constant re-spreading is what drains it; a readiness-loss-by-cause line in api.army(1) would answer that.

## sarmatia (claude-haiku-5-5)

Recruit refusals ("PN is not your city") were the biggest loss: the capital can fall and api.capital never changes, so I kept ordering from a lost city. Please expose the current list of my cities, or let recruit default to any owned city. Depot losses took half the treasury each time; a per-depot or per-province cap on treasury share, or a clear warning when a depot is threatened, would help. Refit refusals (91) happened on units the filter thought were supplied; a plain 'refit-ready' flag would avoid that.

## muscovy (claude-haiku-5-5)

Refused commands dominated the log (24k develop calls at max level, 600 refit calls on units not on supplied land, 1000+ research calls short of rubber). A machine-readable reason in the reply, or a can_dev-style flag for refit and research, would have saved most of this. Upkeep was the main failure: nothing in the briefing tells a commander the purse is draining until it is empty, so a field such as days_left on the rolling view would help. Api.refit_cost per unit and an "in contact" flag on units would let us refit without trial and error.

## anatolia (claude-haiku-5-5)

Upkeep dominated my purse (about 569k of 620k res earned). Per-unit upkeep, and a budget view of how much army the income carries, would help. Research refusals for rubber repeated 10k times because the stock check ignored coal and rubber; a machine-readable refusal reason would prevent this. Engineer fortify orders repeated 93k times with no state change; a 'already fortified' reply would help. api.budget is useful. A per-faction history of discovery prices would make the discovery order easier to plan.

## maghreb (claude-opus-5-5)

It would help to have a 'q depots suggest' query that names provinces where a new depot would cut the most load. The fact that one depot ran at a load of 298 against 60 all war was only visible in the end review. A live warning such as an event 'depot overloaded' would have helped. Also helpful: a road/rail command variant that caps spending ('rail P<a> P<b> max N').

## nilotica (claude-haiku-5-5)

The refit refusal text ("must stand on your own supplied land") is hard to act on from unit rows alone; a unit-level 'supplied' flag that matches the rule would help. Recruit refusals show "need N manpower (have N)" but api.costs seems to hold base manpower, not the price actually charged; exposing the effective price per unit would fix that. A per-tick summary of upkeep versus income for the army (not only the purse totals) would make it easier to cap army size.

## abyssinia (claude-haiku-5-5)

Refused commands that cost us the most: "develop PN is already at the top level" (1,919 times) and "refit must stand on your own supplied land" (528 times). A per-province "can_dev" flag that already includes the room and top-level checks would help. The refit refusal should name the reason (not owned, not supplied, or in contact). Depot choice needs a way to see distance from the enemy front, not just the province list. A short per-hour army summary of units short of supplies would make the front easier to manage. The api.budget days_left figure would be more useful with a note on how much upkeep the current army adds.

## kongo (claude-haiku-5-5)

Group names: "w1"-style names were refused 2,106 times; the rule should state allowed characters. Refit's "must stand on your own supplied land" refusals (about 1,700) were hard to act on: api.provs supplied flag and api.units supplied flag disagree in places. An api.budget field for "net after this recruit" would help set purse limits. Depot losses (11 in one war) would be easier to avoid with a per-depot defence or fort hint. Upkeep per unit kind in api.budget was useful; a per-province upkeep view would help choose where to thin the army.

## austral (claude-opus-5-5)

Useful: a field in api.tree giving the median/most-common age among met factions, so policies can see how far behind they are without guessing from year. Also a "q threats" summary: which met factions border me, their estimated army near my border, and whether we have a pact. The review could show when each depot loss happened relative to who attacked (which faction took it).

## persia (claude-haiku-5-5)

Easier to run: a per-unit upkeep figure and a "units you can afford" number in api (or in q budget) would save hand-computing it. The depot rules are clear, but api.depots does not say which provinces are safe, so I had to guess from borders. Refusals of "recruit: need manpower" were the most common (534) and no api field shows manpower income per day next to unit demand. Attack gating depends on api.model, which is only useful if it is fitted to this war's battles, so a note on that would help.

## arabia (claude-haiku-5-5)

The biggest loss in the last war was upkeep: units cost 31k of 40k res earned and the bank hit zero, and the policy only saw the problem at net -2/day. A per-unit upkeep forecast (what the next recruit adds to net income per day) would help. Depot loss took 100% of the treasury; a line in q budget or api.depots showing treasury at risk per depot would make spreading it easier. Per-assault odds from api.model were not very predictive for us; a fitted model on the unit's own factions would help.

## hindustan (claude-haiku-5-5)

Refit and build refusals were the largest waste. "Must stand on your own supplied land" does not say which of the unit or province is unsupplied, so I had to guess; a per-unit supplied flag that matches the refusal rule would help. Build and develop were refused about 5,000 times as already at the top level, though api.economy shows can_infra/can_dev. Please make that flag match the refusal exactly. Depot losses with 20% of the treasury each time: a per-depot treasury share warning would help. The review's refusal list is useful; a machine-readable reason code per refusal would make it easier to act on.

## turan (claude-haiku-5-5)

Last war the policy was removed for exceeding the time budget: about 2.5M commands, mostly explore and front orders re-issued every tick to units whose standing-order flags did not show them as set. Please document how front, expand and explore appear in api.units, and whether re-issuing a standing order is a no-op. Other gaps: recruit refusals ("is not your city") do not say which provinces are cities, so api.cities or a city flag in api.provs would help. Refit refusals ("must stand on your own supplied land") do not say why a unit failed, e.g. contact or supply. api.tech cost omits coal and rubber in some cases, which caused 472 refusals for research. A cheap call to list my own cities and depots would avoid scanning all provinces every tick.

## siberia (claude-opus-5-5)

A `disband <sel>` command would help: once upkeep outgrows income, there is no way to shrink an oversized, outdated army. Please also show upkeep per unit beside each unit cost in unit_costs, and project how upkeep will change before recruiting.

## yamato (claude-haiku-5-5)

The expand order is the main path to land but it is hard to diagnose: no reason is given when an expand unit does not move or finds no target. A per-unit line in q army saying why it is idle (no reachable neutral land, enemy too close, unsupplied) would help. Also api.powers deposits could show which kinds a faction sells, and offers_out could show whether an offer is still open, not only that it exists.

## oceania (claude-haiku-5-5)

The biggest loss was upkeep: about 9,000 units cost more per day than the whole economy earned, so the purse hit zero by year 1500 and everything else (supplies, readiness, even a nearly free discovery like rocketry) starved. The briefing should say plainly how upkeep scales with unit count, so that a commander can see the break-even army size without trial and error. Also, 'refit' was refused 900+ times because units were not on supplied land; a `q army` line listing refit-eligible units would save many wasted commands. A single border province held 8,674 units at the end, which looks like a front-order artefact; a way to cap stacking per province would help.

## haedong (claude-opus-5-5)

Refit is refused when units stand on land that is not mine, but api.units 'supplied' was True for them. An api flag such as u['own_soil'] or 'can_refit' would help. Please add a disband command so I can shed obsolete units when upkeep eats the income. The review should show the share of income spent on upkeep over time.

