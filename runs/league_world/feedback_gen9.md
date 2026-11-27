## cascadia (claude-opus-5-5)

Last review ran 600 h, so the new tree rules were untested for me. Useful additions:
- A single `q next` or api field naming the cheapest open discovery per age.
- An api.tree flag saying whether a discovery gives a land, sea or air benefit.
- Whether `refit old:<type>` refits all units or only as many as I can afford, and what it returns when it does only part.
- A per-war count of my discoveries next to rivals' ages, shown in the review, to judge my tech pace.

## anahuac (claude-haiku-5-5)

api.tree 'res_now' is not documented as a number or a dict; I had to guess its shape. A one-line example in the docs would help.
api.owner_name shows the owner of provinces I have seen, but there is no direct way to ask whether a faction is at pact with me before trying prepare. A pacts-by-province field, or a flag on api.enemy, would avoid refused commands.
The 'front' order keeps reshuffling units; a garrison order that keeps a fixed number of units in a province would be easier to control.
Refused commands should give a reason in a machine-readable form (e.g. error code), not only text.

## granada (claude-haiku-5-5)

The briefing says research <discovery> is a command, but the tree never appeared in my reviews, and I only found the discovery list through api.tree at runtime. A short line in the review of "discoveries done / pending, and their cost" would help a lot. The review also never showed attacks I prepared and dropped, which makes stalls hard to diagnose; a count of prepared-then-held plans would be useful. Ships and aircraft need a clear note on which cities can recruit them. The economy "already building" refusals could be avoided if api.economy listed the works per province directly.

## andea (claude-haiku-5-5)

Most useful would be a single 'refused' reason string for each failed command, and api.tree showing res_now with strategic purchases broken out. The economy provs list is clear. Two gaps: no field tells whether a province is already being built or queued at the time of a call (we had to infer it from works), and api.research lists discovery names and upgrade lines the same way, so telling them apart needs a check against api.tree. A short note on whether a unit's model is current at recruit time would also help.

## amazonia (claude-opus-5-5)

Please put the discoveries in `api.research` and in the tech results the same way as upgrade lines, and note this in the briefing. Also state in the briefing whether api.research names discoveries.
A `q tree` priority helper would help, as would a per-turn note saying "no research running" when both slots are idle.
Make clear whether `res_now` already includes buying missing strategic resources.
The last war ended at 600 h instead of 9216 h; please say in the review why it ended early.

## albion (claude-haiku-5-5)

Three things would have helped most. 1) A per-tick note of the net income cost of a new unit (upkeep per day by kind is in api.budget, but the cost of one more unit is not stated directly). 2) The 'direct' standing order is hard to track: after a 'move' ends, units show no state for why they stopped. A reason field (arrived / blocked / no route) would help. 3) Neutral land: api.neutral_border was empty for us most of the war, and it was unclear whether that meant no explored free land or no route to it. A clear count of explored neutral provinces reachable by supply would help.

## gallia (claude-haiku-5-5)

The review never shows discovery results or the tree state. Please add a line per discovery (cost paid, what it opened, new model values) to the review, and let api.tree show the 'open' status clearly once prerequisites are met. Group names: 'f<tick>' was refused once with 'bad group name' and the cause was not given; please say which characters or patterns are allowed. Assault results report strength totals only; a per-unit kill count would help. The 'res' figure in api.tree cost is ambiguous about whether lacking strategic resources are included.

## germania (claude-opus-5-5)

It would help if a refused recruit told the policy which discovery is closest to unlocking that kind. A single api call returning "affordable open discoveries sorted by price" would save every agent rebuilding it. The last review covered only 600 h, so it is unclear how representative it is of a 9216 h war; please state the war length in the review header.

## sarmatia (claude-haiku-5-5)

Most useful: a single list of discoveries with their prerequisites and res_now, plus api.tree status for each, is easy to use. The per-line upgrade names (inf.weapons etc.) are not listed anywhere I could find unless q tech is called; a sample name list in the briefing would help. api.enemy 'exact' is only set next to units, so attack-ratio decisions rely on estimates far from the front; an explicit confidence field would help. offers_in kinds for access/supply were unclear. Assault outcome by strength ratio would be good to see live via api.army(1).

## muscovy (claude-haiku-5-5)

Research: api.tree gives status and price per discovery, which is enough to follow the tree, but it would help to have one line per open discovery in the observation (name, cost, days) so a policy does not need to scan the dict. Ancient-age policies (ours) recruit only inf/mil/rec until discoveries land, so an early hint on what each discovery unlocks would help. The per-tick cost of api.tree and api.economy is fine. Attack readiness stats were useful; a live real-assault counter would remove the need to infer them from logs.

## anatolia (claude-haiku-5-5)

The briefing says discoveries open unit kinds, but nothing says how to pick them or whether a 'open' status means affordable now. api.tree's res_now was the clearest signal, so a line stating that 'open' means prerequisites met would help. A ready-made list of ancient/medieval discoveries in tree order would have saved time. api.refit_cost was useful. The front order still reshuffles units, and readiness stays low in contact.

## maghreb (claude-opus-5-5)

It would help to have a clear way to tell discoveries from upgrade lines in api.research: a 'kind' field ('discovery' or 'upgrade') on each entry. Please also give api.tree a ready flag, "affordable now with keep X", or a sorted list of open discoveries by days_of_net_income. A batch refit cost preview, "refit <sel> ?", that returns the total price without spending would be useful. For long wars, the review should show the age reached over time and the upkeep share over time.

## nilotica (claude-haiku-5-5)

1. Undiscovered kinds were refused 96 times by recruit (art before siege_engines). Api.can_raise is useful but the 'not discovered' refusals are not visible in api.can_raise alone; a note in the briefing that recruit only works for kinds in can_raise would help.
2. Research refusals ("need N coal") came from upgrade costs with coal/rubber, which the policy did not check. The per-line cost dict in api.tech could be mentioned as the place to check every key.
3. A list of discoveries open now with their res_now price would save a loop over api.tree; the tree dict is large to scan each tick.
4. The 'hours' field of api.tree is a useful hint for scheduling; please keep it in api.tree for each discovery.

## sahelia (claude-haiku-5-5)

The old policy was removed for the time budget. The likely cause is that per-unit list and set rebuilds (such as set() inside a unit comprehension) plus a unit-by-enemy scan in the planner grow quadratically with a 2000-unit army. A short note in the briefing on expected cost per call would help. Research is hard to script: api.tree lists many discoveries as 'open', but the research slot shares a limit of 2 with upgrades. A line saying whether a discovery occupies a slot would help. Please say whether api.res_now already includes bought strategic resources. api.budget is useful but its days_left semantics (net < 0 only) are easy to misread.

## abyssinia (claude-haiku-5-5)

Discovery picks: api.tree gives res_now but not whether a new model is worth it; a short 'expected gain' hint per discovery would help. api.tree 'missing' lists strategic kinds, but buying them abroad is automatic and the price is only visible through res_now; a line saying so in the briefing would save a lookup. A live count of real assaults (not passing fire) in api.count would help us judge our own attacks.

## kongo (claude-haiku-5-5)

The api.tree and api.research lists are the only way to see the discovery tree, and their status strings ('open', 'known', 'locked', 'researching') are not all listed in the briefing; a short legend would help. api.economy dev_cost/infra_cost are dicts in the example but the briefing's api.provs section still reads like numbers; the mismatch cost one faction its whole economy routine. A per-unit 'dom' flag on api.units would make it easier to keep ships and aircraft out of land recruitment. Pact-by-default diplomacy stalls assaults: a 'pacted' neighbour is excluded from the attack list unless the ratio is 4:1, and most neighbours are pacted.

## austral (claude-opus-5-5)

Shared research slots between discoveries and upgrade lines is unclear: say explicitly whether 2 slots total or 2 each. api.tree res_now is very useful. A field like api.tree[d]['value_hint'] is not wanted (blind is fine), but an api.can_research list would save iteration. Please state whether can_raise includes ship/air kinds before a coastal city exists.

## persia (claude-haiku-5-5)

Most useful: api.tree is easy to use, but 'res_now' is unclear. Say whether it already includes the res needed for a discovery, and whether research of a discovery is refused while another discovery runs. Units the discovery opens (ships, aircraft) need a clear 'can_raise' note on coastal/base requirements. For 'refit', tell us what the cost is when the unit is in a sea zone or in the air. Economy: the 'works' format is clear. Assault gates: a live counter of real assaults (not passing fire) would help a lot.

## arabia (claude-haiku-5-5)

Discoveries: api.tree 'res_now' is clear, but it is not stated whether a discovery's strategic purchases are paid at once; a line in the briefing would help. Research slots: it is unclear whether discoveries and upgrade lines share the 2 slots; api.research rows do not say which kind a row is. Please give the discovery's name in api.research. Recruit refusals return text only; a reason string would help. A per-kind 'can build here' flag (land vs coastal city for ships and aircraft) would avoid trial recruits. Attack stats: a live real-assault counter in api.army would help.

## hindustan (claude-haiku-5-5)

Group names: digits were refused ("bad group name") with no hint of the allowed characters; please state the rule in the briefing.
Discoveries: api.tree shows the price, but the briefing does not say whether a discovery in progress blocks a second one or how many research slots discoveries use. A line in the briefing would help.
Assault results: a "prepared" attack that never launches (plan expired after 20 h) gives no reason in the review; a short reason list would help.
Fronts: the front order reshuffles units every tick; a "hold position" standing order would make garrisons easier to run.
Starting a 2,000-year war with only ancient units is slow to plan; a short tree summary of when cavalry, artillery and navy arrive would help.

## turan (claude-haiku-5-5)

The api.tree entries would be easier to use if res_now were always a plain number (or always a dict); I handle both, but the type varies by reading. The economy works list format [kind, prov, hours] is clear, but a direct "can I develop P<id> now" query would save filtering. A review line that counts refused discovery commands would help, as would a note in the briefing on whether a discovery's bought strategic resources are charged on start or spread over its hours. Thanks for the per-command refusal reasons in the review; they pointed straight at the develop bug.

## siberia (claude-opus-5-5)

The jump to v11 ages broke my old policy quietly: 98 refused recruit commands for kinds not yet discovered. A start-of-war warning listing the kinds a policy tries to raise but cannot would help. Please also show the first exception text for each err_ tally in the review, not just the count. My depot code failed 94 times and I could not see why. A coal market or a clear coal price would help, since develop needs coal and many factions have none.

## zhongyuan (claude-haiku-5-5)

The briefing says research picks discoveries, but the upgrade table and api.tech only cover upgrade lines. Discoveries are only visible through api.tree and api.known, which is easy to miss, and my first policy never researched one. A sample of api.tree and the research result format would help. The 'group' verb rejected my group names with 'bad group name' without saying what a valid name is. Please list the allowed name format. api.research does not say whether it includes discoveries, so I count running discoveries by status 'researching' instead.

## yamato (claude-haiku-5-5)

Income went negative by day 5 because the starting army's upkeep was larger than the land could pay, and there is no way to reduce upkeep except by losing units. A per-unit upkeep field in api.units, or a total upkeep forecast, would help a lot. api.can_raise and api.costs only show raisable kinds, so the era of the army is hard to read; a field for the current era would help. The 'expand' order reports no reason when neutral land is out of reach. Trade and supply deal formats are clear, but a rate hint (res per strategic unit) would make pricing easier. Discovery results only show up in tech events; a short api.tree result with 'known' and 'effect' would help.

## nusantara (claude-haiku-5-5)

Research: api.research lists only upgrade lines. Please say in the briefing or in api.research whether a discovery in progress shows there too, or only as status 'researching' in api.tree. I had to infer it.
Recruit mix: a placeholder share is needed to keep the mix tidy; a 'can_raise' share helper would help.
api.economy: works entries are easy to read, but a single list of provinces with can_dev/can_infra is the right shape. Thanks.
Discoveries needing strategic resources: the auto-buy price is only visible via api.tree cost. A one-line note in the briefing would help.
The 2,000-year span: please document the 'era' field (api.age is the age of the latest discovery, not the calendar era).

## oceania (claude-haiku-5-5)

Most useful: a short api.tree entry per discovery saying whether it is affordable now, and what it opens, so the policy need not hard-code tree order. Also: the research refusal "need N res (have N)" came up 20 times; the reason is unclear (a reserve? a price change?). Please state which in the message. Upgrade results do not say which line they affect until the breakthrough is reported. Attack outcomes only reach the policy as summaries; a live counter of real assaults (not passing fire) would help. Ships and aircraft lack a documented base/sea-zone recruit path in the briefing; a one-line example would help.

## haedong (claude-opus-5-5)

Please clarify whether the 2 research slots are shared between discoveries and upgrade lines. Please also state whether api.tree res_now already includes the 10%-per-faction discount. A field like api.tree[d]['eta_days'] in budget terms would help. For refits, a dry-run or cost-total query (e.g. 'q refit old') would help. A live counter of real assaults launched and won would still be very useful.

