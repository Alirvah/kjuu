from django.urls import path
from . import views

app_name = 'queueapp'

urlpatterns = [
    path('', views.home, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
	path('logout/', views.logout_view, name='logout'),
	path('privacy/', views.privacy, name='privacy'),
	path('terms/', views.terms, name='terms'),
	path("delete-account/", views.delete_account, name="delete_account"),
    path('queue/create/', views.create_queue, name='create_queue'),
    path('queue/<str:short_id>/join/', views.join_queue, name='join_queue'),
    path('queue/<str:short_id>/dashboard/', views.queue_dashboard, name='queue_dashboard'),
    path('queue/<str:short_id>/leave/', views.leave_queue, name='leave_queue'),
    path('queue/<str:short_id>/delete/', views.delete_queue, name='delete_queue'),
    path('queue/<str:short_id>/call_next/', views.call_next, name='call_next'),
    path('queue/<str:short_id>/pause/', views.pause_queue, name='pause_queue'),
    path('queue/<str:short_id>/qr/', views.download_queue_qr, name='qr_queue'),
    path('queue/go/', views.go_to_queue, name='go_to_queue'),
    path('q/<slug:short_id>/register_key/', views.register_public_key, name='register_public_key'),
    path('q/<slug:short_id>/submit_info/',  views.submit_info, name='submit_info'),
    path('q/<slug:short_id>/clear_info/', views.clear_info, name='clear_info'),

]

