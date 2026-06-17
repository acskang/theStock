#!/bin/bash
set -e

echo "=============================="
echo "  Stock Workbench 설치 시작"
echo "=============================="

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 가 필요합니다."
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py makemigrations
python manage.py migrate
python manage.py seed_symbols

if [ -f stock_history_refined.csv ]; then
  echo "CSV 자동 import 진행 중..."
  python manage.py import_stock_csv stock_history_refined.csv || true
fi

echo ""
read -p "관리자 계정을 생성하시겠습니까? (y/n): " CREATE_SUPER
if [ "$CREATE_SUPER" = "y" ] || [ "$CREATE_SUPER" = "Y" ]; then
  python manage.py createsuperuser
fi

echo "=============================="
echo "설치 완료"
echo "source .venv/bin/activate"
echo "python manage.py runserver"
echo "샘플 데이터: python manage.py seed_averaging_demo"
echo "관리자: http://localhost:8000/admin/"
echo "=============================="
