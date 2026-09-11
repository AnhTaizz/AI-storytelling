# H6b Critic Comparison

## Frozen Reference
On this frozen RUN3 reference set, there are a total of 33 robust primary gold issues, spanning 20 units. There is 1 additional QUESTIONABLE issue used for sensitivity analysis, making a total of 34 candidate issues.

## Matching Policy
A prediction matches a gold issue only if it identifies substantially the same material factual/epistemic problem. If a prediction explicitly flags multiple independent atomic assertions correctly, it is mapped to multiple gold issues (counting as detected once for each unique gold issue). 

## Critic V1 Metrics
- **Total Problematic Predictions:** 2
- **TP Robust:** 2
- **FP:** 0
- **Primary Precision:** 1.0000
- **Primary Recall:** 0.0606
- **Primary F1:** 0.1143
- **Unit Recall:** 0.1000

## RUN7 Metrics
- **Total Problematic Predictions:** 9
- **TP Robust:** 9
- **FP:** 0
- **Primary Precision:** 1.0000
- **Primary Recall:** 0.3333
- **Primary F1:** 0.5000
- **Unit Recall:** 0.4000

## Observed Comparison
- **Recall absolute difference:** 0.2727
- **Recall ratio:** 5.5000
- **Precision difference:** 0.0000
- **F1 difference:** 0.3857

On this frozen RUN3 reference set, RUN7 detected substantially more robust gold issues than Critic V1 while both had no mapped false positives under the frozen adjudication.

## Classification Agreement
For both Critic V1 and RUN7, the exact classification agreement for all matched robust gold issues was 1.0000. 

## Severity Agreement
- **Critic V1:** 0.5000 (1 exact match out of 2 comparable gold issues)
- **RUN7:** 0.5455 (6 exact matches out of 11 comparable gold issues)

## False Positives
- **Critic V1:** None
- **RUN7:** None

## False Negatives

### Critic V1 (31 Missed)
- `G001` (P002): [UNSUPPORTED] Mahiru lives in the apartment immediately to the right of Amane's room.
- `G002` (P003): [UNSUPPORTED] Mahiru has a high elegant nose.
- `G003` (P003): [UNSUPPORTED] Mahiru has long eyelashes.
- `G005` (P006): [UNSUPPORTED] Amane avoids getting involved with Mahiru because he fears jealousy from other boys.
- `G006` (P006): [UNSUPPORTED] Amane only considers Mahiru as a piece of art to admire from afar.
- `G008` (P011): [STRONGER_THAN_BRIEF] Mahiru has no intention of finding shelter.
- `G009` (P011): [STRONGER_THAN_BRIEF] Mahiru looks with lifeless/soulless eyes.
- `G010` (P011): [UNSUPPORTED] Mahiru's face is pale from the cold.
- `G011` (P012): [STRONGER_THAN_BRIEF] Amane is certain Mahiru will catch a cold.
- `G012` (P013): [UNSUPPORTED] Amane assumes Mahiru wants to stay/get soaked in the rain.
- `G013` (P014): [UNSUPPORTED] Amane scratches his head and pulls his ears in frustration.
- `G015` (P015): [UNSUPPORTED] Amane intentionally tries to keep his tone cold so Mahiru won't misunderstand.
- `G016` (P017): [UNSUPPORTED] Mahiru startles.
- `G017` (P017): [UNSUPPORTED] Mahiru is pale.
- `G018` (P018): [UNSUPPORTED] Amane and Mahiru often run into each other in the morning.
- `G019` (P020): [UNSUPPORTED] Amane is surprised that Mahiru remembers his last name.
- `G020` (P020): [STRONGER_THAN_BRIEF] Mahiru is always bothered by boys.
- `G021` (P020): [UNSUPPORTED] Mahiru's wariness is a natural consequence of frequently being bothered by boys.
- `G022` (P020): [UNSUPPORTED] Amane assumes Mahiru thinks he is using this opportunity to hit on her.
- `G023` (P021): [UNSUPPORTED] Amane shrugs.
- `G024` (P024): [UNSUPPORTED] Amane knows Mahiru has something heavy on her mind.
- `G025` (P025): [UNSUPPORTED] Amane is inherently someone who fears trouble.
- `G026` (P025): [UNSUPPORTED] Amane's conscience only compelled him to ask a single question as its maximum limit.
- `G027` (P025): [UNSUPPORTED] Amane can leave completely free of guilt after asking his question.
- `G028` (P026): [UNSUPPORTED] Mahiru is sitting huddled/curled up.
- `G029` (P027): [STRONGER_THAN_BRIEF] Amane is certain she will get sick if she stays like this.
- `G030` (P028): [UNSUPPORTED] Amane leaves before Mahiru can open her mouth to object.
- `G031` (P029): [UNSUPPORTED] Amane doesn't care what Mahiru says.
- `G032` (P030): [UNSUPPORTED] Amane believes he has done his best/utmost.
- `G033` (P030): [STRONGER_THAN_BRIEF] Giving the umbrella completely washed away all his guilt/troubled conscience.
- `G034` (P031): [UNSUPPORTED] Amane believes Mahiru generally does not want anything to do with him.

### RUN7 (22 Missed)
- `G006` (P006): [UNSUPPORTED] Amane only considers Mahiru as a piece of art to admire from afar.
- `G008` (P011): [STRONGER_THAN_BRIEF] Mahiru has no intention of finding shelter.
- `G009` (P011): [STRONGER_THAN_BRIEF] Mahiru looks with lifeless/soulless eyes.
- `G011` (P012): [STRONGER_THAN_BRIEF] Amane is certain Mahiru will catch a cold.
- `G012` (P013): [UNSUPPORTED] Amane assumes Mahiru wants to stay/get soaked in the rain.
- `G013` (P014): [UNSUPPORTED] Amane scratches his head and pulls his ears in frustration.
- `G014` (P014): [STRONGER_THAN_BRIEF] Amane is certain he will lose sleep tonight out of guilt.
- `G016` (P017): [UNSUPPORTED] Mahiru startles.
- `G020` (P020): [STRONGER_THAN_BRIEF] Mahiru is always bothered by boys.
- `G021` (P020): [UNSUPPORTED] Mahiru's wariness is a natural consequence of frequently being bothered by boys.
- `G023` (P021): [UNSUPPORTED] Amane shrugs.
- `G024` (P024): [UNSUPPORTED] Amane knows Mahiru has something heavy on her mind.
- `G025` (P025): [UNSUPPORTED] Amane is inherently someone who fears trouble.
- `G026` (P025): [UNSUPPORTED] Amane's conscience only compelled him to ask a single question as its maximum limit.
- `G027` (P025): [UNSUPPORTED] Amane can leave completely free of guilt after asking his question.
- `G028` (P026): [UNSUPPORTED] Mahiru is sitting huddled/curled up.
- `G029` (P027): [STRONGER_THAN_BRIEF] Amane is certain she will get sick if she stays like this.
- `G030` (P028): [UNSUPPORTED] Amane leaves before Mahiru can open her mouth to object.
- `G031` (P029): [UNSUPPORTED] Amane doesn't care what Mahiru says.
- `G032` (P030): [UNSUPPORTED] Amane believes he has done his best/utmost.
- `G033` (P030): [STRONGER_THAN_BRIEF] Giving the umbrella completely washed away all his guilt/troubled conscience.
- `G034` (P031): [UNSUPPORTED] Amane believes Mahiru generally does not want anything to do with him.

## Sensitivity Analysis
Including the 1 QUESTIONABLE issue (`G007`) in the gold denominator (N=34):
- **Critic V1 Sensitivity Recall:** 0.0588
- **RUN7 Sensitivity Recall:** 0.3235

Neither critic detected the questionable issue, nor did they make any sensitivity-only predictions. Since there are no sensitivity-only predictions and no false positives, the sensitivity precision equals the primary precision (1.0000) for both critics.

## Schema Violation Note and Protocol Limitations
### RUN7 Limitations
- Mechanical unit coverage confirmed at 32/32 units.
- Claim count confirmed at 49 claims.
- Schema conformance is `false`. One invalid claim type (`OBSERVATION`, id: `C025`) was produced, which is invalid under Prompt V3. 
- Strict machine context isolation is `NOT_VERIFIABLE`.
- Results are from 1 real semantic primary attempt with 0 quality-based regenerations.

### Critic V1 Limitations
- Critic V1 was not deterministic claim-by-claim. It produced a small free-form violation set (2 factual/epistemic violation predictions).
- Strict machine context isolation was not independently enforced.
- It was part of the H6 Critic + Revision pipeline. This comparison evaluates useful detection coverage, not identical output format.

## H6b Hypothesis Verdict
**PENDING_ORCHESTRATOR_REVIEW**
