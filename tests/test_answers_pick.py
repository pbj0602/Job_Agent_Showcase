from job_agent.answers import NEEDS_HUMAN, plan

QUESTIONS = [
    {"label": "First Name", "required": True, "type": "input_text"},
    {"label": "Email", "required": True, "type": "input_text"},
    {"label": "Resume/CV", "required": True, "type": "input_file"},
    {"label": "Will you require our company to sponsor you to obtain work authorization?", "required": True,
     "type": "multi_value_single_select"},
    {"label": "If you replied yes to the question above, please explain.", "required": False, "type": "input_text"},
    {"label": "Are you presently authorized to work for our company?", "required": True, "type": "multi_value_single_select"},
    {"label": "Were you referred by a current employee?", "required": True, "type": "multi_value_single_select"},
    {"label": "Why do you want to work here?", "required": True, "type": "textarea"},
]


def test_fill_plan(vault, countries):
    answers = vault.yaml("answers.yml")
    p = plan(QUESTIONS, answers, countries["UK"], cv_path="cv.pdf")
    def by(pl):
        return {s.label.split()[0] + " " + s.label.split()[-1] if len(s.label.split()) > 1 else s.label: s.value
                for s in pl.steps}

    v = by(p)
    assert v["First Name"] == "Alex" and v["Resume/CV"] == "cv.pdf"
    assert v["Will authorization?"] == "Yes" and v["Are company?"] == "No"
    assert v["Were employee?"] == "No"
    assert [s.label for s in p.blockers] == ["Why do you want to work here?"] and not p.auto_ok
    se = by(plan(QUESTIONS, answers, countries["SE"]))
    assert se["Will authorization?"] == "No" and se["Are company?"] == "Yes"
    assert se["Resume/CV"] == NEEDS_HUMAN
    ie = by(plan(QUESTIONS, answers, countries["IE"]))
    assert ie["Will authorization?"] == "No" and ie["Are company?"] == "No"


def test_prepare_answers_sheet():
    from job_agent.prepare import answers_md, slug
    job = {"company": "Acme", "title": "SWE Intern (m/f/d)", "country_code": "NL", "ats": "workday",
           "url": "https://x.example/job", "jd": "Internship (6 months), start in June."}
    answers = {"rules": [{"match": "start date", "answer": "June 2027"}]}
    md = answers_md(job, answers, {"sponsor_needed": True, "presently_authorised": False, "employer_action": "TWV"})
    assert "| Will you now or in the future require visa sponsorship? | No |" in md  # the rule in answers.yml
    assert "| Earliest start date | June 2027 |" in md and "Internship (6 months)" in md
    assert "要注册账号" in md and "TWV" in md
    assert slug(job).endswith("-acme-nl-swe-intern-m-f-d")


def test_season():
    from job_agent.season import season
    assert season("Intern", "This is a 12 week paid summer internship program")[0] == "summer"
    assert season("Intern", "Internship lengths are either 3 or 12 months")[0] == "summer"  # the short option fits
    assert season("Intern", "The start date will be January 2027 for a duration of 6 months. Summer fun!")[0] == "off"
    assert season("Praktikum", "Wir suchen ab dem 15. Januar 2027 für 6 Monate Unterstützung")[0] == "off"
    assert season("Intern", "Availability to work at least 20 hours per week")[0] == "off"
    assert season("Intern", "We retain your data for 12 months")[0] == "unknown"
    assert season("Intern (3 months)", "Human Resources Intern (12 months)")[0] == "summer"


def test_pick_decides_all_and_dream(store):
    from datetime import date
    from job_agent.pick import pick, ready_to_apply
    for i in range(5):
        store.add({"id": f"p{i}", "company": f"Co{i}", "title": "Software Engineer Intern", "country_code": "SE",
                   "season": "summer", "role": "swe"}, actor="route")
        store.move(f"p{i}", "approved", actor="route", force=True)
    store.add({"id": "g", "company": "Google", "title": "SWE Intern", "country_code": "SE", "role": "swe"}, actor="route")
    store.move("g", "approved", actor="route", force=True)
    policy = {"pick": {"daily_auto": 3, "per_company": 3}, "auto_tailor_roles": ["swe"]}
    day = date(2026, 11, 1)
    first = pick(store, policy, ["Google"], day)
    assert len(first["auto"]) == 5 and [j["id"] for j in first["careful"]] == ["g"]  # every job gets a decision
    assert pick(store, policy, ["Google"], day)["auto"] == []  # nothing left to decide
    j = store.get(first["auto"][0]["id"])
    assert not ready_to_apply(j, day) and ready_to_apply(j, date(2026, 11, 2))  # veto window: until the next day


def test_pick_company_quota_waits_and_role_order(store):
    from datetime import date
    from job_agent.pick import pick
    for i in range(4):
        store.add({"id": f"a{i}", "company": "Acme", "title": f"SWE Intern {i}", "country_code": "SE",
                   "season": "summer", "role": "swe"}, actor="route")
        store.move(f"a{i}", "approved", actor="route", force=True)
    store.add({"id": "pm", "company": "Beta", "title": "Product Manager Intern", "country_code": "UK",
               "season": "unknown", "role": "pm"}, actor="route")
    store.move("pm", "approved", actor="route", force=True)
    policy = {"pick": {"per_company": 3}, "auto_tailor_roles": ["swe", "pm"], "role_order": ["pm", "swe"]}
    out = pick(store, policy, [], date(2026, 11, 2))
    assert out["auto"][0]["id"] == "pm"  # the user's direction order beats summer-confirmed and country order
    assert len(out["auto"]) == 4 and out["no"] == []
    waiting = [j for j in store.all() if j["company"] == "Acme" and not j.get("decision")]
    assert len(waiting) == 1 and waiting[0]["status"] == "approved"  # over the quota: waits, not 不投
