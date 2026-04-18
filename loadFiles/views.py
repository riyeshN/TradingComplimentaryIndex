from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import logging
import json
from loadFiles.services.TradeMapExcelData import TradeMapExcelData
from loadFiles.services.ComtradeDownload import ComtradeReferenceData, ComtradeTradeData

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

def extract_data_from_trade_map_excel(request):
    if request.method == "GET":
        trade_map_excel_data = TradeMapExcelData()
        trade_map_excel_data.process_calculate_trading_complimentary_index()
        return JsonResponse({"status":"Success"}, status=200)

    else:
        return HttpResponse("Method not allowed", status=405)