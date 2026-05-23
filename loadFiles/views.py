from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import logging
import json
from loadFiles.services.TCICalculator import TCICalculator
from loadFiles.services.TradeMapLoader import TradeMapLoader
from loadFiles.services.ComtradeDownload import ComtradeReferenceData, ComtradeTradeData
from loadFiles.services.scope import SCOPES_BY_NAME

# Create your views here.
logger = logging.getLogger(__name__)

def update_reference_for_country_id(request):
    if request.method == "GET":
        comtrade_ref_data = ComtradeReferenceData()
        comtrade_ref_data.get_updated_reference_data_for_country_name()
        return JsonResponse({"status":"Success"}, status=200)
    else:
        return HttpResponse("Fail", status=400)

@csrf_exempt
def fetch_trade_data(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            comtrade_trade_data = ComtradeTradeData(
                reporter=data.get("reporter", []),
                partner=data.get("partner", []),
                trade_type=data.get("trade_type", "C"),
                frequency=data.get("frequency", "A"),
                year_period=data.get("year_period", []),
                cmd_code=data.get("cmd_code", "AG6"),
                flow_code=data.get("flow_code", "2")
            )
            comtrade_trade_data.fetch_trade_data()
            return JsonResponse({"status": "Success"}, status=200)
        except Exception as e:
            logger.error(f"Error in fetch_trade_data: {e}")
            return JsonResponse({"status": "Error", "message": str(e)}, status=400)
    else:
        return HttpResponse("Method not allowed", status=405)

@csrf_exempt
def calculate_tci(request):
    if request.method not in ("GET", "POST"):
        return HttpResponse("Method not allowed", status=405)

    countries = None
    hs4_codes = None
    scope_arg = "ict"
    if request.method == "POST":
        body = json.loads(request.body or b"{}")
        countries = body.get("countries") or None
        hs4_codes = body.get("hs4_codes") or None
        scope_arg = body.get("scope") or "ict"

    if scope_arg == "all":
        scopes_to_run = list(SCOPES_BY_NAME.values())
    else:
        if scope_arg not in SCOPES_BY_NAME:
            return JsonResponse(
                {"status": "Error", "message": f"unknown scope '{scope_arg}'; expected one of "
                                               f"{list(SCOPES_BY_NAME) + ['all']}"},
                status=400,
            )
        scopes_to_run = [SCOPES_BY_NAME[scope_arg]]

    for scope in scopes_to_run:
        TCICalculator(scope=scope).run(countries=countries, hs4_codes=hs4_codes)
    return JsonResponse(
        {"status": "Success", "scopes_run": [s.name for s in scopes_to_run]},
        status=200,
    )

def load_trade_data_to_db(request):
    if request.method == "GET":
        try:
            TradeMapLoader().load()
            return JsonResponse({"status": "Success"}, status=200)
        except Exception as e:
            logger.error("Error in load_trade_data_to_db: %s", e)
            return JsonResponse({"status": "Error", "message": str(e)}, status=500)
    else:
        return HttpResponse("Method not allowed", status=405)