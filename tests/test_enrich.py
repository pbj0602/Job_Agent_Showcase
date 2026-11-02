from job_agent.enrich.language import language_required
from job_agent.enrich.sponsorship import Register, duration_days, jd_signal, judge
from job_agent.geo import country_of


def test_real_uk_jds_saying_no_sponsorship(samples):
    for r in samples:
        if r.get("sponsorship") == "no":
            verdict, evidence = jd_signal(r["jd"])
            assert verdict == "no", r["company"]
            assert "sponsor" in evidence


def test_signal_variants():
    assert jd_signal("Candidates must already have the right to work in the Netherlands.")[0] == "no"
    assert jd_signal("We offer relocation and visa support for interns.")[0] == "yes"
    assert jd_signal("Visa sponsorship is available for this programme.")[0] == "yes"
    assert jd_signal("We build payment software.")[0] is None


def test_duration():
    assert duration_days("a 10-12 week summer internship") == 84
    assert duration_days("Duration: 6 months, starting July") == 180
    assert duration_days("founded 120 years ago") is None


def test_judge_country_rules(countries):
    se = judge("SE", countries, "Must have the right to work in Sweden.", "Spotify", big=True)
    assert se.verdict == "not_needed"
    assert judge("ES", countries, "", "X", big=True).verdict == "no"
    assert judge("UK", countries, "We are unable to provide visa sponsorship.", "Arm", big=True).verdict == "no"
    assert judge("UK", countries, "Great internship.", "Google", big=True).verdict == "likely"
    assert judge("NL", countries, "Great internship.", "TinyCo", big=False).verdict == "unclear"
    assert judge("IE", countries, "This is an unpaid internship.", "X", big=False).verdict == "no"
    long_ie = judge("IE", countries, "A 6 months internship.", "X", big=True)
    assert long_ie.verdict == "unclear" and "90" in long_ie.reason
    assert judge("SE", countries, "EU citizens only.", "X", big=False).verdict == "no"


def test_register_lookup(tmp_path, countries):
    p = tmp_path / "uk.csv"
    p.write_text("Organisation Name,Town/City\nBloomberg Finance L.P.,London\nArm Limited,Cambridge\n")
    reg = Register.from_csv("UK licensed sponsors", p, "Organisation Name")
    assert reg.has("Arm") and reg.has("ARM Ltd") and reg.has("Bloomberg")
    assert not reg.has("Armada")
    v = judge("UK", countries, "Nice role", "Arm", big=False, registers={"uk": reg})
    assert v.verdict == "likely" and "register" in " ".join(v.evidence)


def test_language():
    assert language_required("Fluent German (C1) is required for this role.")[0][0] == "German"
    assert language_required("Dutch is a plus. English is required.") == []
    assert language_required("You will work at a Dutch university spin-off.") == []


def test_geo():
    assert country_of("Belfast, Northern Ireland") == "UK"
    assert country_of("Dublin, Ireland") == "IE"
    assert country_of("Dublin, OH") is None
    assert country_of("München, Bayern") == "DE"
    assert country_of("Zürich, Switzerland") == "CH"
    assert country_of("Remote") is None
