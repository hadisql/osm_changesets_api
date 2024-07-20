
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from changesets.views import APILandingPageView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('changesets.urls')),
    path('', APILandingPageView.as_view(), name='api-landing-page'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

