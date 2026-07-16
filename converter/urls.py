from django.urls import path

from . import views

app_name = 'converter'

urlpatterns = [
    path('', views.index_view, name='index'),
    path('api/converter', views.api_pdf_ofx_converter, name='api_converter'),
    path('api/<uuid:download_id>/baixar', views.api_pdf_ofx_download, name='api_download'),
]
