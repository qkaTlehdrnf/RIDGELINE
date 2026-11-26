## cascadia (claude-opus-5-5)

The format of api.economy "dev_cost" / "infra_cost" (a number or a dict) is not stated; please document it. A way to queue several develop levels in one province would help, as would an api field giving the current score and rank. It would also help to know why most front units never meet attack conditions, for example a tally of visible enemy provinces next to the border per faction.

## laurentia (claude-haiku-5-5)

Laurentia ended with 32k res unspent and the unit cap reached, so the economy commands were not exercised by the old policy; a 'q economy' line in the review (what was built, what each level cost) would help. Refit: 1242 of 2417 units stayed on old models, and the rule (not on border, not in contact, readiness 50+) rarely fires for a front-heavy army. A refit-queue or 'q army' line showing units blocked by each condition would make this easier to tune. Assault stats were 0/5 on defended provinces with 1-2 defenders; the per-assault line in REVIEW: full helps. The unit cap is a policy choice, not a rule, so a clearer note on what upkeep costs per unit would help agents size armies.

## anahuac (claude-haiku-5-5)

Assaults: the review says "none taken" but gives no reason why plans fail. A per-plan log (ratio, model p, launch or cancel) in api.army or the review would help me tune thresholds without guessing.
Refit: refit only works out of combat, and 594 units stayed outdated. A query listing which old units are blocked and why (contact, unsupplied, low strength) would help.
Units in contact 94% of the time: a "contact" flag per province in api.army(1) would show which fronts are truly static.
api.tech_log gives results but not the unrevealed line depth; that is fine, but a note on how many levels remain would help prioritise research.

## granada (claude-haiku-5-5)

The trade syntax was easy to misread: "trade A X for B Y" means the partner gives A X and you give B Y, but our own offers show up in the log under the opposite labels ("they give / you give"), which made it look as if we were selling steel. Please document the direction in the briefing, or log offers as "you give / they give" from the proposer's side. api.economy provs fields (dev_cost, infra_cost, room) were not documented with types; a sample line in the briefing would help. A per-tick attack diagnostic would have shown why no assault reached the threshold: the strike logic gives no reason when it declines.

## andea (claude-haiku-5-5)

1) api.economy provs: please document the type of dev_cost (dict or number) and what "room" means (share, or levels).
2) offers_in: clarify whether they_give is what the proposer gives us or what we give. Our trade logic depends on it.
3) Scouts sent to front do not give exact enemy counts unless adjacent. A short "watch" standing order would help.
4) Steel and oil were zero all war; the research lines needing them block silently. A list of the lines we can start now would help.

## amazonia (claude-opus-5-5)

Documenting that tick is called only at t % 6 == 0 would help. My earlier conditions like t%12==9 and t%24==3 silently never fired, so depots and refits never happened in two wars. A warning when a policy never issues some command type would also help. The format of economy dev_cost/infra_cost (dict or number) is unclear.

## platina (claude-haiku-5-5)

The API is mostly clear. Friction points: (1) api.economy provs and works formats are not documented, so I guessed field names (prov, room, infra) and had to code defensively; a one-line example would help. (2) The strike gate depends on api.model, which is a fixed logistic fit; it would help to know its training range, since I had to guess whether a 3:1 ratio is outside it. (3) A per-province line in the review showing why an assault was not launched (probability, ratio, fort) would make tuning much faster than inferring it from outcomes. (4) api.count names are capped at 60; that is fine, but the cap is not stated in the review section.

## albion (claude-haiku-5-5)

Useful: a per-province list of stock, inflow and burn in api.units or api.army (level 2 is good but costly to call every tick). Unclear: the field types of api.economy provs (dev_cost, infra_cost), and the exact definition of plan 'bonus' and 'dirs' in api.model. Missing: a way to cap how many units the 'front' standing order sends to one province; it currently piles onto the single remaining border province when the border shrinks. Good to have: a single command that moves a group to a province and holds it on arrival.

## gallia (claude-haiku-5-5)

Losing the only depot wiped the whole treasury (38 res left). A simple way to see every depot's stock and what a depot loss would cost would help. api.economy provs dev_cost/infra_cost are not documented as plain numbers or dicts; please state the type. The `room` field's meaning (raw slots or a share) is unclear. A per-enemy-province "exact" flag in api.enemy is referenced in the briefing but its reliability is not spelled out. The assault stats were hard to read; a single fail/success ratio per attack size would help.

## iberia (claude-haiku-5-5)

1. api.economy provs: dev_cost and infra_cost formats are unclear (dict, number, or per-level?). Please document them.
2. Oil and coal shortfalls were hard to see early. A single line in the daily summary, e.g. "oil stock 0, income 0, units blocked by oil", would help.
3. The 'front' standing order keeps reshuffling units, so attacks rarely form. A "hold a reserve of N units at the capital" option would be useful.
4. Assault statistics mixed passing fire with real attacks. Separate counts would make reviews easier.

## germania (claude-opus-5-5)

Please state the exact format of economy dev_cost and infra_cost (a number or a dict) in the briefing. A per-province "why this yield" breakdown would also help to judge whether develop pays back before upkeep.

## scandia (claude-haiku-5-5)

The economy layer was hard to build blind: api.economy 'works' and 'provs' entries are not documented as tuples or dicts (I guessed works[i][1] is the province), and dev_cost/infra_cost are shown as fields but their format is unclear. A short example in the briefing would help. api.pacts kind values ('pact', 'alliance', 'truce') should be listed in the API section. The 'depot' and 'develop' cost formulas are stated per level, which is clear, but a q command that prints the next-level cost for one province would save a lot of guessing. Assault statistics are hard to act on: the review counts passing fire as assaults, so the 'assaults' figure misleads the agent about how often attacks happen.

## muscovy (claude-haiku-5-5)

The economy tools work but are hard to plan with: api.economy['provs'] does not show the development or infrastructure cost in a plain number, so each agent has to guess the coal and steel needed. A single 'can afford' query for develop and build (for example q econ-cost P<id>) would help. api.army's front block is useful, but the review's 'assaults in numbers' stat counts passing fire as assaults, which misleads the agent into thinking attacks happen more often than they do. Separating real assaults from exchanges of fire in both the live api and the review would fix this. 'q powers' is also hard to read when many factions have been met.

## anatolia (claude-haiku-5-5)

Policies run every 6 h, so any "one action per call" logic is throttled to about 4 actions a day; a per-call batch limit or a way to get a shorter tick would help. api.unit_costs does not say whether 'res' already includes upkeep, and api.economy provs lacks a clear field for the cost of the next level (dev_cost/infra_cost form is unclear). Units bought before a refit keep old values, so a note in api.refit_cost on whether a new model is ready would help. The review's 'assault' count includes passing fire, which misleads the agent into thinking attacks are common.

## maghreb (claude-opus-5-5)

Please document the exact format of economy provs dev_cost and infra_cost: is it a number or a dict, and which resources does it include? A helper that returns the cheapest affordable develop target would save a lot of guesswork. The review would be more useful if it split income into territory yield and unit upkeep, so we can see when the army is eating the economy.

## nilotica (claude-haiku-5-5)

Economy: api.economy provs lacks a stated unit for dev_cost/infra_cost; a plain cost number per level would help. api.me is described both as faction name and as player id; a separate api.me_id would avoid guessing. api.me_id_hint() appears in the policy examples but not in the API, so it fails silently; it should be documented or removed. A per-war summary of how many assaults the fitted model accepted or rejected would help tune thresholds.

## sahelia (claude-haiku-5-5)

The economy layer is hard to use blind. The format of api.economy provs (dev_cost, infra_cost) is not documented exactly, so I guessed between number and dict. Please document it. The assault statistics also mix passing fire with real attacks, so it is hard to tell from the review whether a plan really moved in. A per-plan result line (plan target, units sent, outcome) would help. Finally, api.army(1) by_order does not say which units are inside a plan, which would help debugging.

## abyssinia (claude-haiku-5-5)

Easier to run: (1) api.economy provs lacks a clear 'cost to next level' per unit of stock; dev_cost and infra_cost are fine but their keys (res, coal, steel) should be documented in the snapshot. (2) The assault odds model is trained on earlier battles and the 'dirs' feature is hard to interpret; a note on its typical range would help. (3) The review's 'passing fire' versus real assault distinction is only visible after the war; a live counter of real assaults in api.army would let agents judge their own attacks. (4) Refit cost and the 35% rule are clear, but how many units can be refitted per tick without stalling is not stated.

## kongo (claude-haiku-5-5)

Economy: api.economy provs lists dev_cost but not the coal cost of the next level; a field such as dev_coal would help. Calls to api.provs for enemy land are sparse, so the attack estimate often falls back to UNSEEN_DEF; a per-province last-seen strength would help. The review lists 46 fire exchanges "left out" of the assault table; it would help to see those too. Rubber piles up unused for most factions; a clearer hint about which lines use it would help.

## austral (claude-opus-5-5)

Please document the exact format of api.economy provs fields "room" and "dev_cost" (number or dict). Also say whether the assault readiness buckets in the review mean readiness at launch or averaged over the assault. A `q econ best` query that ranks develop/build options by yield gain per cost would help.

## persia (claude-haiku-5-5)

Steel ran to zero in every war while oil and res piled up, and the API gives no way to see steel income or ask for it except by trade; a q-line showing each faction's steel and oil surplus would help. Assault results are hard to act on: the review shows failures but not why a ratio was judged enough, and api.model's bonus input is always zero for us. Clear per-province lines for "which of my provinces could sustain an attack" would help more than the current totals. The `trial` command is useful but I have not yet found a cheap way to use it inside a 5-second commander loop.

## arabia (claude-haiku-5-5)

Attack planning is hard to tune from the summary alone. Per-province tallies of planned vs. launched vs. won assaults with their force sizes would help. The api.model win estimate is opaque: a short table of its predictions against real outcomes would show whether to trust it. The review's "3 units vs 3 defenders" median hides whether groups were split across provinces. A single command to merge a scattered set of units into one formation before an assault would also save a lot of manual sequencing.

## hindustan (claude-haiku-5-5)

Economy is hard to run blind: api.economy provs gives dev_cost/infra_cost, but the format (dict or number, key names) is not stated in the briefing. Please document it. The assault statistic 'median size 1 units' is misleading when units pass through on move orders; a 'real assault' count would help. A q command that lists pacts by kind and expiry together with access deals would save calls.

## turan (claude-haiku-5-5)

api.economy['provs'] does not document the format of dev_cost (dict or scalar) or whether 'prov' is the key; a one-line example would help. api.army(1) by_order and front fields are useful, but a per-target 'contact' or 'shelling' view would help explain failed assaults. The 'assaults' stat counts passing fire, which misleads. Please separate assault launches from exchanges of fire in the review. Assault median-size reporting is good; a per-attack record of the units that reached the target would be better.

## siberia (claude-opus-5-5)

The review should say why depot commands failed. I had a single depot at 144/60 load all war and could not tell why no others opened. Per-command rejection reasons would help, at least the top five texts. A field that says directly whether a province is a legal depot site would also help. A trade market, or standing offers anyone can see, would make swapping resources much easier than guessing who has steel.

## nusantara (claude-haiku-5-5)

Rubber piled up unused (4,674 at war end) while steel and oil ran short; a per-line view of which resources each line can use, given current stock, would make such mismatches easier to spot. A "q army" field for the tick a wave was blocked (ratio, readiness, stock) would help tune attacks without guessing. api.count works but is capped at 60 names and reviews only show totals; per-tick timelines of tallies would be useful. The `front` standing order reshuffles units, which costs readiness; an explicit "garrison here" order would help.

## oceania (claude-haiku-5-5)

api.economy['works'] and api.economy['provs'] field formats are not documented precisely (is works a list of [kind, prov, hours] lists?); a single line per field in the briefing would help. dev_cost and infra_cost are not clearly typed (number or dict of resources). Trial results should show the cost of a develop or build before it is ordered. Assault stats were useful; a per-war readiness distribution for units near the border would help diagnose why front units decay.

## haedong (claude-opus-5-5)

Depot load is easy to miss: the only warning that my one depot ran at 94/60 came in the review. A live event when a depot passes capacity would help. Also unclear: whether api.army(0) "dry" counts units or provinces.

