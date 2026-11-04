# 🔴⚪ Kalendar utakmica Crvene zvezde

Pretplata na kalendar: https://toniristic.github.io/crvena-zvezda-calendar/crvena_zvezda.ics

Generator čita aktuelni [klupski raspored](https://www.crvenazvezdafk.com/sr-latn/raspored-rezultati) za sva prikazana takmičenja, uključujući evropska. Za Superligu prednost imaju datum i satnica u [rasporedu FSS za sezonu 2026/27](https://fss.rs/takmicenje/mozzart-bet-super-liga-srbije-26-27/?script=lat). Klupska potvrđena satnica dopunjuje FSS samo ako oba izvora navode isti datum. Stara vest sa okvirnim rasporedom i TheSportsDB više se ne koriste.

- Potvrđen početak upisuje se u UTC; aplikacija ga prikazuje u svojoj vremenskoj zoni. Izvori za ove utakmice prikazuju satnice po vremenu u Beogradu. Trajanje od dva sata je procena.
- Nepoznata satnica (`.`, prazno, `00:00`) prikazuje se kao celodnevni događaj sa oznakom **satnica nije potvrđena**, statusom `TENTATIVE` i isključivim završnim datumom narednog dana. Ne izmišlja se 09:00. Objavljeni datum ostaje podložan promeni.
- Novi UID zasniva se na sezoni takmičenja, takmičenju, kolu/fazi i uređenom paru timova, bez datuma i vremena početka. Različite sezone i takmičenja imaju različite identitete.
- Postojeće utakmice pri prelasku na novu verziju zadržavaju već objavljene UID vrednosti, uključujući njihov stari tekst sa datumom. Te vrednosti su od sada nepromenljive; `X-MATCH-ID` čuva novi identitet. Promena termina ili prelazak sa celodnevnog na vremenski događaj podiže `SEQUENCE`. Nepromenjen raspored ne menja sadržaj ICS-a ni vremenske oznake.
- Ako izvor nije dostupan, struktura rasporeda više ne odgovara parseru ili iz narednog rasporeda nestane prethodno objavljena buduća utakmica, generator se završava greškom i ostavlja postojeći ICS. Ne objavljuje nepotpun kalendar. Nestanak utakmice zahteva proveru zvanične odluke o otkazivanju pre ručne izmene prethodnog feeda.
- ICS se proverava ponovnim parsiranjem, proverom UID jedinstvenosti, intervala i vremenskih zona, pa se zamenjuje atomskom operacijom.

## Pokretanje

Python 3.12 ili noviji:

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
python generate_calendar.py
```

Podrazumevana sezona određuje se po vremenu u Beogradu (jul–jun); sezona u identifikatoru pripada takmičenju, a ne datumu pojedinačne utakmice. Za ručni izbor:

```sh
python generate_calendar.py --season 2026-27 --output crvena_zvezda.ics
```

Dnevno GitHub Actions ažuriranje ostaje u **04:00 UTC** (05:00 zimi / 06:00 leti u Beogradu), uz ručno pokretanje `workflow_dispatch`. Izmena generatora, zavisnosti, testova ili workflow-a na `main` takođe pokreće proveru i osvežavanje. Pull request pokreće samo testove. U repozitorijum se automatski upisuje samo `crvena_zvezda.ics`.

Testovi koriste HTML snimke zvaničnih izvora od 4. novembra 2026. sa uklonjenim dekorativnim elementima i utakmicama drugih timova. Proveravaju evropske mečeve, ispravku Vojvodine, prvenstvo FSS, nepoznatu satnicu, migraciju starih UID vrednosti, promenu termina, letnje vreme, duplikate i očuvanje feeda pri grešci.

Postojeću pretplatu na isti URL treba zadržati; izmene će stići pri sledećem osvežavanju aplikacije. Jednokratno uvezeni ICS fajlovi se ne ažuriraju automatski.
