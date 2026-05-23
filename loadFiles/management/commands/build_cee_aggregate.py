"""
Build the CEE importer aggregate from individual TradeMap country files.

For the Yang (2023) cross-validation, the partner is the Central & Eastern
European country group. TradeMap's own pre-built "CEE" aggregate
(`china_CCE.txt`) under-captures CEE commodity imports, which biased the
primary-section complementarity indices low. This command instead reconstructs
the group as the **sum of the 17 countries Yang actually uses** (her "17+1"
framework), from one TradeMap "Existing and potential trade between China and
{country}" file per country.

Only the importer side is rebuilt: each country's **imports from world** by HS6
are summed per `(product_code, year)` (the HS6 rows give M_b^k; the `TOTAL` row
gives M_b). The result replaces the `partner='CCE'` rows in
`PartnerImportFromWorld`. China's exports (reporter side) and `WorldExport` are
untouched, so the rest of the Yang pipeline and all ICT/strategic runs are
unaffected.

Usage:
    python manage.py build_cee_aggregate
    python manage.py build_cee_aggregate --dir data/TradeMapData/cee_countries --partner CCE
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from loadFiles.models import PartnerImportFromWorld

DEFAULT_DIR = "data/TradeMapData/cee_countries"
# Yang (2023) Tables 1–2, the "17+1" CEE framework (Greece included).
EXPECTED_COUNTRIES = 17


def _import_from_world_long(path: Path) -> pd.DataFrame:
    """Melt one TradeMap bilateral file's 'imports from world' columns to long
    `(product_code, year, value_usd_thousands)`. Keeps the TOTAL row."""
    raw = pd.read_csv(path, sep='\t')
    hs_code_column = raw.columns[0]
    import_columns = [c for c in raw.columns if "imports from world" in str(c).lower()]
    if not import_columns:
        raise CommandError(f"No 'imports from world' columns in {path.name}")
    year_rename = {
        col: col.split("Value in ")[-1].split(",")[0].strip()
        for col in import_columns
    }
    subset = raw[[hs_code_column] + import_columns].rename(columns=year_rename)
    year_columns = [c for c in subset.columns if c != hs_code_column and str(c).isdigit()]
    return (
        subset[[hs_code_column] + year_columns]
        .melt(id_vars=[hs_code_column], var_name='year', value_name='value_usd_thousands')
        .dropna(subset=['value_usd_thousands'])
        .rename(columns={hs_code_column: 'product_code'})
        .assign(
            product_code=lambda frame: frame['product_code'].astype(str).str.strip(),
            year=lambda frame: frame['year'].astype(int),
        )
    )


class Command(BaseCommand):
    help = "Rebuild the CEE importer aggregate by summing per-country TradeMap files."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=DEFAULT_DIR,
                            help=f"Folder of per-country TradeMap files (default {DEFAULT_DIR}).")
        parser.add_argument("--partner", default="CCE",
                            help="Partner name to write into PartnerImportFromWorld (default CCE).")

    def handle(self, *args, **options):
        source_dir = Path(options["dir"])
        partner = options["partner"]
        if not source_dir.is_dir():
            raise CommandError(f"Directory not found: {source_dir}")

        files = sorted(p for p in source_dir.iterdir() if p.suffix == '.txt' and not p.name.startswith('._'))
        if not files:
            raise CommandError(f"No .txt files in {source_dir}")

        per_country = []
        for path in files:
            country_long = _import_from_world_long(path)
            country_name = path.stem.split("China_and_")[-1]
            year_min, year_max = country_long['year'].min(), country_long['year'].max()
            self.stdout.write(
                f"  {country_name:<26} rows={len(country_long):>6}  years={year_min}-{year_max}"
            )
            per_country.append(country_long)

        if len(files) != EXPECTED_COUNTRIES:
            self.stdout.write(self.style.WARNING(
                f"Found {len(files)} files (expected {EXPECTED_COUNTRIES} for Yang's CEE group)."
            ))

        aggregate = (
            pd.concat(per_country, ignore_index=True)
            .groupby(['product_code', 'year'], as_index=False)['value_usd_thousands']
            .sum()
        )

        objects = [
            PartnerImportFromWorld(
                partner=partner,
                product_code=row['product_code'],
                year=int(row['year']),
                value_usd_thousands=float(row['value_usd_thousands']),
            )
            for row in aggregate.to_dict('records')
        ]
        with transaction.atomic():
            PartnerImportFromWorld.objects.filter(partner=partner).delete()
            PartnerImportFromWorld.objects.bulk_create(objects, batch_size=1000)

        total_2021 = aggregate[
            (aggregate['product_code'].str.upper() == 'TOTAL') & (aggregate['year'] == 2021)
        ]['value_usd_thousands']
        total_note = f"{total_2021.iloc[0]:.0f} (USD thousands)" if len(total_2021) else "n/a"
        self.stdout.write(self.style.SUCCESS(
            f"Rebuilt partner '{partner}' from {len(files)} countries: "
            f"{len(objects)} rows. 2021 CEE TOTAL imports = {total_note}."
        ))
