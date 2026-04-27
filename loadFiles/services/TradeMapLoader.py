import shutil
import logging
import pandas as pd
from pathlib import Path

TSV_DATA_DIRECTORY = "./data/TradeMapData/data/"


class TradeMapLoader:
    """Parses TradeMap TSV files and bulk-loads them into the database."""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def load(self):
        """Parse all TSV files in the data directory, upsert to DB, then archive each file."""
        from django.db import transaction
        from loadFiles.models import (
            HSProduct, CountryExportToWorld, CountryExportToPartner,
            PartnerImportFromWorld, WorldExport,
        )

        data_dir = Path(TSV_DATA_DIRECTORY)
        if not data_dir.exists():
            self.logger.error("Data directory not found: %s", TSV_DATA_DIRECTORY)
            return

        hs_code_to_label:                    dict[str, str]      = {}
        world_export_dataframes:             list[pd.DataFrame]  = []
        reporter_export_to_world_dataframes: list[pd.DataFrame]  = []
        reporter_export_to_partner_dataframes: list[pd.DataFrame] = []
        partner_import_from_world_dataframes: list[pd.DataFrame] = []
        successfully_parsed_file_paths:      list[Path]          = []

        for tsv_file_path in data_dir.iterdir():
            if not (tsv_file_path.is_file() and tsv_file_path.suffix == '.txt' and not tsv_file_path.name.startswith('._')):
                continue
            try:
                if 'world' in tsv_file_path.name.lower():
                    hs_codes, world_export_long = self._parse_world_file(tsv_file_path)
                    world_export_dataframes.append(world_export_long)
                else:
                    hs_codes, reporter_export_to_partner, reporter_export_to_world, partner_import_from_world = self._parse_bilateral_file(tsv_file_path)
                    reporter_export_to_partner_dataframes.append(reporter_export_to_partner)
                    reporter_export_to_world_dataframes.append(reporter_export_to_world)
                    partner_import_from_world_dataframes.append(partner_import_from_world)

                hs_code_to_label.update(hs_codes)
                successfully_parsed_file_paths.append(tsv_file_path)
                self.logger.info("Parsed: %s", tsv_file_path.name)
            except Exception as e:
                self.logger.error("Error reading %s: %s", tsv_file_path.name, e)

        with transaction.atomic():
            self._upsert_hs_products(hs_code_to_label)
            self._upsert(WorldExport,            world_export_dataframes,               ['product_code', 'year'])
            self._upsert(CountryExportToWorld,   reporter_export_to_world_dataframes,   ['reporter', 'product_code', 'year'])
            self._upsert(CountryExportToPartner, reporter_export_to_partner_dataframes, ['reporter', 'partner', 'product_code', 'year'])
            self._upsert(PartnerImportFromWorld, partner_import_from_world_dataframes,  ['partner', 'product_code', 'year'])

        archive_dir = data_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        for processed_file in successfully_parsed_file_paths:
            shutil.move(str(processed_file), str(archive_dir / processed_file.name))

        self.logger.info("Load complete — %d file(s) processed and archived.", len(successfully_parsed_file_paths))

    # ── Parsers ──────────────────────────────────────────────────────────────

    def _parse_world_file(self, path: Path) -> tuple[dict[str, str], pd.DataFrame]:
        raw_tsv = pd.read_csv(path, sep='\t')
        hs_code_column, label_column = raw_tsv.columns[0], raw_tsv.columns[1]

        year_column_rename_map = {
            col: int(col.lower().split("value in")[-1].split(",")[0].strip())
            for col in raw_tsv.columns
            if "value in" in col.lower()
            and col.lower().split("value in")[-1].split(",")[0].strip().isdigit()
        }
        raw_tsv.rename(columns=year_column_rename_map, inplace=True)
        year_integer_columns = [c for c in raw_tsv.columns if isinstance(c, int)]

        hs_code_to_label = {
            str(product_code).strip(): str(product_label).strip().strip('"')
            for product_code, product_label in zip(raw_tsv[hs_code_column], raw_tsv[label_column])
            if str(product_code).strip().upper() != 'TOTAL'
        }

        world_export_long = (
            raw_tsv[[hs_code_column] + year_integer_columns]
            .melt(id_vars=[hs_code_column], var_name='year', value_name='value_usd_thousands')
            .dropna(subset=['value_usd_thousands'])
            .rename(columns={hs_code_column: 'product_code'})
            .assign(product_code=lambda row: row['product_code'].astype(str).str.strip())
        )
        return hs_code_to_label, world_export_long

    def _parse_bilateral_file(
        self, path: Path
    ) -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        reporter, partner = path.stem.split("_")[0], path.stem.split("_")[1]
        raw_tsv = pd.read_csv(path, sep='\t')
        hs_code_column, label_column = raw_tsv.columns[0], raw_tsv.columns[1]

        hs_code_to_label = {
            str(product_code).strip(): str(product_label).strip().strip('"')
            for product_code, product_label in zip(raw_tsv[hs_code_column], raw_tsv[label_column])
            if str(product_code).strip().upper() != 'TOTAL'
        }

        def _extract_and_melt_flow(flow_columns: list[str], flow_keyword: str) -> pd.DataFrame:
            trade_flow_subset = raw_tsv[[hs_code_column] + flow_columns].dropna(axis=1, how='all')
            year_column_rename_map = {
                col: col.split("Value in ")[-1].split(",")[0].strip()
                for col in trade_flow_subset.columns if flow_keyword in col.lower()
            }
            trade_flow_subset = trade_flow_subset.rename(columns=year_column_rename_map)
            year_integer_columns = [c for c in trade_flow_subset.columns if c != hs_code_column and str(c).isdigit()]
            return (
                trade_flow_subset[[hs_code_column] + year_integer_columns]
                .melt(id_vars=[hs_code_column], var_name='year', value_name='value_usd_thousands')
                .dropna(subset=['value_usd_thousands'])
                .rename(columns={hs_code_column: 'product_code'})
                .assign(
                    product_code=lambda row: row['product_code'].astype(str).str.strip(),
                    year=lambda row: row['year'].astype(int),
                )
            )

        export_to_partner_columns = [c for c in raw_tsv.columns if "exports to" in c.lower() and "world" not in c.lower()]
        export_to_world_columns   = [c for c in raw_tsv.columns if "exports to world" in c.lower()]
        import_from_world_columns = [c for c in raw_tsv.columns if "imports from world" in c.lower()]

        reporter_export_to_partner = _extract_and_melt_flow(export_to_partner_columns, "exports to").assign(reporter=reporter, partner=partner)
        reporter_export_to_world   = _extract_and_melt_flow(export_to_world_columns,   "exports to world").assign(reporter=reporter)
        partner_import_from_world  = _extract_and_melt_flow(import_from_world_columns, "imports from world").assign(partner=partner)

        return hs_code_to_label, reporter_export_to_partner, reporter_export_to_world, partner_import_from_world

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _upsert_hs_products(self, hs_code_to_label: dict[str, str]):
        from loadFiles.models import HSProduct
        HSProduct.objects.bulk_create(
            [HSProduct(product_code=product_code, product_label=product_label) for product_code, product_label in hs_code_to_label.items()],
            update_conflicts=True,
            unique_fields=['product_code'],
            update_fields=['product_label'],
            batch_size=1000,
        )
        self.logger.info("Upserted %d records into HSProduct.", len(hs_code_to_label))

    def _upsert(self, model, trade_flow_dataframes: list[pd.DataFrame], unique_fields: list[str]):
        if not trade_flow_dataframes:
            return
        combined_records = pd.concat(trade_flow_dataframes, ignore_index=True).drop_duplicates(subset=unique_fields, keep='last')
        model_fields = {f.attname for f in model._meta.concrete_fields if f.attname != 'id'}
        combined_records = combined_records[[c for c in combined_records.columns if c in model_fields]]
        model_instances = [model(**row) for row in combined_records.to_dict('records')]
        model.objects.bulk_create(
            model_instances,
            update_conflicts=True,
            unique_fields=unique_fields,
            update_fields=['value_usd_thousands'],
            batch_size=2000,
        )
        self.logger.info("Upserted %d records into %s.", len(model_instances), model.__name__)
