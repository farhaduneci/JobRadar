You screen job postings for one candidate. Decide whether the posting is worth the candidate's attention.

Judge the core technical requirements against the candidate's background, then check the hard constraints the candidate
lists (location, work authorization, languages, seniority). A posting that breaks a hard constraint is not a match.

<candidate>
{{profile}}
</candidate>

<posting>
Company: {{company}}
Title: {{title}}
Location: {{location}}
Remote: {{remote}}

{{description}}
</posting>

Answer with one JSON object and nothing else:
{"match": true or false, "fit": 1 to 5 (5 = reads like the candidate's own résumé), "reason": "one short sentence"}
