## What this changes

<!-- Pull requests are not being merged yet: the public API is pre-1.0 and still
     moving, so a patch against it may not survive the month. See CONTRIBUTING.md.
     This form is here because a pull request that arrives anyway should carry
     what a reviewer would otherwise have to ask for, and it will be read.

     One paragraph below: what the reader gets that they did not have. -->

## Why

<!-- The defect, the gap, or the case that motivated it. If it fixes an issue,
     link it: Closes #N. -->

## Kind of change

- [ ] Bug fix
- [ ] New capability
- [ ] Documentation
- [ ] Breaking change to a supported name
- [ ] Other

## Evidence

<!-- How do you know it works? Prefer output over description. -->

- [ ] A test that **fails without this change**. If the test passes both before
      and after, it is not evidence yet — the quickest proof is to revert the
      change and watch it go red.
- [ ] For a checker change: the envelope before and after, including
      `not_checked`. A finding that appears is only half the claim; the declines
      it stopped or started producing are the other half.
- [ ] For anything touching the eleven supported names or `arbiter_engine.api`:
      said so explicitly below.

```

```

## Supported surface

<!-- Eleven names are a contract; everything deeper is importable and
     unpromised. Which did you touch? -->

- [ ] Supported surface unchanged
- [ ] Supported surface changed — described above, and why it could not be done
      behind it

## Checklist

- [ ] Read [CONTRIBUTING.md](CONTRIBUTING.md)
- [ ] Agree to the [Code of Conduct](CODE_OF_CONDUCT.md)
- [ ] Licensed under Apache-2.0, per [LICENSE](LICENSE)
- [ ] If AI-assisted: reviewed the generated content and accept it as my own
      contribution, per [AI_ATTRIBUTION.md](AI_ATTRIBUTION.md)

## Anything reviewers should know
