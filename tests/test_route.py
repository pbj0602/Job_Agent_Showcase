from job_agent.config import load_pack
from job_agent.route import decide, required_language

POLICY = {"auto_tailor_roles": ["swe", "pm", "data", "ml", "proj"], "calibration_reviews": 2}
JD = "We are a startup of 25 people. " + "We build distributed systems in Python and Java. " * 20


def run(countries, applied=0, **job):
    base = dict(company="TinyCo", title="Software Engineer Intern", country_code="SE", jd=JD,
                url="https://jobs.lever.co/tinyco/1", ats="lever")
    base.update(job)
    return decide(base, countries=countries, roles=load_pack("roles"), policy=POLICY, applied_so_far=applied)


def test_small_swedish_company_calibrates_then_autos(countries):
    assert run(countries).status == "awaiting_confirm"
    assert run(countries, applied=5).status == "approved"


def test_big_company_always_confirms(countries):
    d = run(countries, company="Spotify", applied=99)
    assert d.status == "awaiting_confirm" and d.fields["size"] == "big"


def test_size_needs_evidence(countries):
    plain = "We build distributed systems in Python and Java. " * 20
    assert run(countries, jd=plain, applied=99).fields["size"] == "unknown"
    assert run(countries, jd=plain, applied=99).status == "approved"   # unknown size = not well-known = auto
    assert run(countries, company="Tesla Germany GmbH", applied=99).fields["size"] == "big"
    assert run(countries, jd=JD + " Join our 12,000 employees.", applied=99).fields["size"] == "big"
    assert run(countries, company="Acme AG", applied=99).fields["size"] == "big"
    assert run(countries, url="https://acme.wd3.myworkdayjobs.com/x").fields["size"] == "big"
    assert run(countries, company="Step Recruitment Ltd").status == "manual"


def test_hard_stops(countries):
    assert run(countries, title="Master Thesis: LLM agents").status == "thesis"
    assert run(countries, title="Werkstudent Software (m/w/d)", country_code="DE").status == "skipped"
    assert run(countries, jd=JD + " Fluent Swedish is required.").status == "skipped"
    assert run(countries, country_code="ES").status == "skipped"


def test_needs_a_human(countries):
    assert run(countries, country_code="NL").status == "manual"          # route pending in NL
    assert run(countries, country_code="UK").status == "skipped"         # small UK company: never sponsors
    assert run(countries, title="IT Audit Intern", jd="ISO 27001 controls audit " * 30).status == "manual"
    assert run(countries, ats="linkedin", url="https://linkedin.com/jobs/1").status == "manual"
    assert run(countries, jd="short").status == "manual"


def test_real_amazon_uk_record(countries, samples):
    from job_agent.sources import digest_queue  # noqa: F401  (record shape matches the digest)
    rec = {"company": "Amazon", "title": "2027 Software Dev Engineer Intern - United Kingdom",
           "country_code": "UK", "jd": JD, "url": "https://www.amazon.jobs/en/jobs/10581332", "ats": "other"}
    d = decide(rec, countries=countries, roles=load_pack("roles"), policy=POLICY)
    assert d.status == "awaiting_confirm" and d.fields["visa_verdict"] == "likely"


def test_mandatory_and_stale_season(countries):
    pol = {**POLICY, "season_year": 2027}
    roles = load_pack("roles")

    def d(**job):
        base = dict(company="Bosch", title="Software Intern", country_code="DE", jd=JD, url="u", ats="other")
        base.update(job)
        return decide(base, countries=countries, roles=roles, policy=pol)

    assert d(title="Mandatory Internship in Software Testing").status == "skipped"
    assert d(jd="Pflichtpraktikum für Studierende. " + JD).status == "skipped"
    assert d(jd="Pflichtpraktikum oder freiwilliges Praktikum. " + JD).status != "skipped"
    assert d(title="Software Engineering Intern (2026)").status == "manual"
    assert d(title="Software Engineering Intern 2027").status == "awaiting_confirm"


def test_title_decides_role(countries):
    jd = "project milestones stakeholder coordination budget delivery risk vendor timeline " * 5
    assert run(countries, title="Compliance Internship", jd=jd).fields["role"] == "grc"


def test_role_packs_cover_non_swe(countries):
    assert run(countries, title="Product Manager Intern", jd="roadmap user research stakeholders " * 20).fields["role"] == "pm"
    assert run(countries, title="Quantitative Trader Intern", jd="probability options market making " * 20).fields["role"] == "quant"


def test_new_grad_roles_skipped_for_later_graduates(countries):
    pol = {**POLICY, "graduation_year": 2028}
    go = lambda title: decide(dict(company="TinyCo", title=title, country_code="SE", jd=JD, ats="lever",
                                   url="https://jobs.lever.co/x/1"), countries=countries,
                              roles=load_pack("roles"), policy=pol).status
    assert go("Software Engineer, New Grad") == "skipped"
    assert go("2027 Early Career Software Engineer") == "skipped"
    assert go("2027 – Graduate or Internship, Infrastructure Engineer") != "skipped"
    assert go("Graduate Software Engineering Intern") != "skipped"


def test_big_company_auto_when_policy_says_so(countries):
    d = decide(dict(company="Spotify", title="Software Engineer Intern", country_code="SE", jd=JD, ats="lever",
                    url="https://jobs.lever.co/x/1"), countries=countries, roles=load_pack("roles"),
               policy={**POLICY, "auto_apply_big": True}, applied_so_far=99)
    assert d.status == "approved" and d.fields["size"] == "big"


def test_required_language_only_when_required():
    L = ["C", "C++"]
    assert required_language("Requirements:\n- Strong C++ skills\n- Linux", L) == "C++"
    assert required_language("- Strong programming skills in C/C++", L) == "C"
    assert required_language("Nice to have:\n- C++\n- Rust", L) == ""
    assert required_language("Proficiency in Python. C++ is a plus.", L) == ""
    assert required_language("Proficiency with Java, Python, C/C++", L) == ""  # a menu of languages
    assert required_language("We raised a Series C. Strong Python required.", L) == ""
    assert required_language("Requires access to controlled technology (15 C.F.R. 734).", L) == ""
    assert required_language("Experience with C# and .NET required.", L) == ""


def test_skip_list_from_policy(countries):
    skip = {"roles": ["quant"], "titles": ["designer|marketing"], "jd": ["security clearance"],
            "required_languages": ["C++"]}
    go = lambda **kw: decide(dict(dict(company="TinyCo", title="Software Engineer Intern", country_code="SE",
                                       jd=JD, ats="lever", url="https://jobs.lever.co/x/1"), **kw),
                             countries=countries, roles=load_pack("roles"),
                             policy={**POLICY, "skip": skip}, applied_so_far=99).status
    assert go() == "approved"
    assert go(title="Product Designer Intern") == "skipped"
    assert go(title="Quantitative Trader Intern") == "skipped"
    assert go(jd=JD + "\nSecurity clearance is required.") == "skipped"
    assert go(jd=JD + "\nRequirements:\n- Strong C++ skills") == "skipped"


def test_role_only_in_some_countries(countries):
    pol = {**POLICY, "auto_tailor_roles": POLICY["auto_tailor_roles"] + ["consulting"],
           "skip": {"only_in": [{"match": "consult", "roles": ["consulting"], "countries": ["SE"]}]}}
    go = lambda cc: decide(dict(company="TinyCo", title="Strategy Consultant Intern", country_code=cc, jd=JD,
                                ats="lever", url="https://jobs.lever.co/x/1"), countries=countries,
                           roles=load_pack("roles"), policy=pol, applied_so_far=99).status
    assert go("SE") != "skipped"
    assert go("DE") == "skipped"


def test_country_order():
    from job_agent.geo import country_rank
    order = [["SE"], ["DE", "IE", "NL"], ["UK"]]
    assert [country_rank(order, c) for c in ("SE", "NL", "UK", "PL")] == [0, 1, 2, 3]
