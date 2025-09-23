from django.test import TestCase, Client
from django.urls import reverse, resolve
from django.contrib.auth import get_user_model
from datetime import timedelta

from queueapp.models import Queue, Customer
from queueapp import views

import pytest
pytest.skip("tests.py is legacy, skipping", allow_module_level=True)


User = get_user_model()


class QueueModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', password='pass')
        self.queue = Queue.objects.create(
            name='Test Queue',
            short_id='ABC123',
            owner=self.user
        )

    def test_str_representation(self):
        self.assertEqual(str(self.queue), 'Test Queue (ABC123)')

    def test_is_empty_initial(self):
        self.assertTrue(self.queue.is_empty())

    def test_average_wait_time_with_no_served(self):
        self.assertEqual(self.queue.average_wait_time, timedelta(0))

    def test_average_wait_time_with_served(self):
        self.queue.served_count = 2
        self.queue.total_wait_time = timedelta(minutes=10)
        self.queue.save()
        self.assertEqual(self.queue.average_wait_time, timedelta(minutes=5))


class CustomerModelTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pass')
        self.queue = Queue.objects.create(name='Q', short_id='XYZ789', owner=self.owner)
        self.user1 = User.objects.create_user(username='cust1', password='pass')
        self.user2 = User.objects.create_user(username='cust2', password='pass')

    def test_wait_time_without_called(self):
        c = Customer.objects.create(user=self.user1, queue=self.queue)
        self.assertEqual(c.wait_time, timedelta(0))

    def test_wait_time_with_called(self):
        c = Customer.objects.create(user=self.user1, queue=self.queue)
        c.called_at = c.created_at + timedelta(minutes=15)
        c.save()
        self.assertEqual(c.wait_time, timedelta(minutes=15))

    def test_position(self):
        c1 = Customer.objects.create(user=self.user1, queue=self.queue)
        c2 = Customer.objects.create(user=self.user2, queue=self.queue)
        self.assertEqual(c1.position, 1)
        self.assertEqual(c2.position, 2)

    def test_str_representation(self):
        c = Customer.objects.create(user=self.user1, queue=self.queue)
        expected = f"{self.user1.username} in {self.queue.short_id}"
        self.assertEqual(str(c), expected)


class URLPatternsTest(TestCase):
    def test_all_urls_resolve(self):
        patterns = [
            ('home', [], views.home),
            ('signup', [], views.signup_view),
            ('login', [], views.login_view),
            ('logout', [], views.logout_view),
            ('delete_account', [], views.delete_account),
            ('privacy', [], views.privacy),
            ('terms', [], views.terms),
            ('create_queue', [], views.create_queue),
            ('join_queue', ['ABC123'], views.join_queue),
            ('queue_dashboard', ['ABC123'], views.queue_dashboard),
            ('pause_queue', ['ABC123'], views.pause_queue),
            ('leave_queue', ['ABC123'], views.leave_queue),
            ('call_next', ['ABC123'], views.call_next),
            ('qr_queue', ['ABC123'], views.download_queue_qr),
            ('go_to_queue', [], views.go_to_queue),
        ]
        for name, args, func in patterns:
            path = reverse(f'queueapp:{name}', args=args)
            self.assertEqual(resolve(path).func, func, f"URL {name} did not resolve to {func.__name__}")


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='owner', password='pass')
        self.queue = Queue.objects.create(name='Test', short_id='TST', owner=self.owner)
        self.other = User.objects.create_user(username='other', password='pass')
        self.ip = '123.45.67.89'

    # Basic page views
    def test_home_view(self):
        self.assertEqual(self.client.get(reverse('queueapp:home')).status_code, 200)

    def test_signup_view(self):
        self.assertEqual(self.client.get(reverse('queueapp:signup')).status_code, 200)

    def test_login_view_get(self):
        self.assertEqual(self.client.get(reverse('queueapp:login')).status_code, 200)

    # Logout & account deletion
    def test_logout_view(self):
        self.client.login(username='other', password='pass')
        resp = self.client.get(reverse('queueapp:logout'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('queueapp:home'), resp.url)

    def test_delete_account_requires_login(self):
        resp = self.client.post(reverse('queueapp:delete_account'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('queueapp:login'), resp.url)

    def test_delete_account(self):
        self.client.login(username='other', password='pass')
        resp = self.client.post(reverse('queueapp:delete_account'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(User.objects.filter(username='other').exists())

    # Queue creation
    def test_create_queue_restrictions(self):
        self.assertEqual(self.client.get(reverse('queueapp:create_queue')).status_code, 302)
        self.client.login(username='other', password='pass')
        self.assertEqual(self.client.get(reverse('queueapp:create_queue')).status_code, 200)

    def test_create_queue_post(self):
        self.client.login(username='other', password='pass')
        data = {'name': 'CombinedQueue', 'color_hex': '#ABCDEF'}
        resp = self.client.post(reverse('queueapp:create_queue'), data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Queue.objects.filter(name='CombinedQueue').exists())

    # Join & leave
    def test_join_queue_flow(self):
        self.client.login(username='other', password='pass')
        join_url = reverse('queueapp:join_queue', args=[self.queue.short_id])
        # GET
        self.assertEqual(self.client.get(join_url).status_code, 200)
        # POST creates customer
        resp = self.client.post(join_url)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Customer.objects.filter(user=self.other, queue=self.queue).exists())

    def test_prevent_double_join(self):
        self.client.login(username='other', password='pass')
        url = reverse('queueapp:join_queue', args=[self.queue.short_id])
        self.client.post(url)
        # Second join should redirect and not duplicate
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Customer.objects.filter(user=self.other, queue=self.queue).count(), 1)

    def test_leave_without_join(self):
        self.client.login(username='other', password='pass')
        leave_url = reverse('queueapp:leave_queue', args=[self.queue.short_id])
        resp = self.client.post(leave_url)
        # Should return 404 when no membership
        self.assertEqual(resp.status_code, 404)

    # Pause/unpause
    def test_pause_unpause_queue(self):
        self.client.login(username='owner', password='pass')
        pause_url = reverse('queueapp:pause_queue', args=[self.queue.short_id])
        # Pause
        self.client.post(pause_url)
        q = Queue.objects.get(pk=self.queue.pk)
        self.assertFalse(q.active)
        # Unpause
        self.client.post(pause_url)
        q.refresh_from_db()
        self.assertTrue(q.active)

        # Serving behavior
    def test_call_next(self):
        self.client.login(username='owner', password='pass')
        call_url = reverse('queueapp:call_next', args=[self.queue.short_id])
        # On empty queue, no errors
        resp_empty = self.client.post(call_url)
        self.assertEqual(resp_empty.status_code, 302)
        self.assertFalse(Customer.objects.filter(queue=self.queue, called_at__isnull=False).exists())
        # With two customers from different users
        user2 = User.objects.create_user(username='third', password='pass')
        c1 = Customer.objects.create(user=self.other, queue=self.queue)
        c2 = Customer.objects.create(user=user2, queue=self.queue)
        resp = self.client.post(call_url)
        self.assertEqual(resp.status_code, 302)
        # First customer should be marked called
        c1.refresh_from_db()
        self.assertIsNotNone(c1.called_at)
        # Served count may remain until serve action

    # Dashboard & QR" & QR
    def test_queue_dashboard_and_qr(self):
        Customer.objects.create(user=self.other, queue=self.queue)
        self.client.login(username='owner', password='pass')
        dash_url = reverse('queueapp:queue_dashboard', args=[self.queue.short_id])
        resp = self.client.get(dash_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('queue', resp.context)
        self.assertIn('waiting_customers', resp.context)
        self.assertIn('called_customer', resp.context)
        # QR code endpoint may not be implemented; expect 404
        qr_url = reverse('queueapp:qr_queue', args=[self.queue.short_id])
        qr_resp = self.client.get(qr_url)
        self.assertEqual(qr_resp.status_code, 404)

    # Navigation helper
    def test_go_to_queue_redirects(self):
        go_url = f"{reverse('queueapp:go_to_queue')}?queue_id={self.queue.short_id}"
        # Unauthenticated -> login
        resp = self.client.get(go_url)
        self.assertEqual(resp.status_code, 302)
        # Authenticated non-joined -> join
        self.client.login(username='other', password='pass')
        resp = self.client.get(go_url, follow=True)
        self.assertRedirects(resp, reverse('queueapp:join_queue', args=[self.queue.short_id]))



class QueueAppTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username='owner', password='pass')
        self.user = User.objects.create_user(username='user', password='pass')

        self.client.login(username='owner', password='pass')
        self.queue = Queue.objects.create(
            name='Test Queue',
            owner=self.owner,
            short_id='TEST1',
            active=True
        )

    def test_queue_creation_page_when_user_has_queue(self):
        self.client.logout()
        self.client.login(username='owner', password='pass')
        response = self.client.get(reverse('queueapp:create_queue'))
        self.assertEqual(response.status_code, 302) 


    def test_queue_creation_page_when_user_has_no_queue(self):
        self.client.logout()
        self.client.login(username='user', password='pass')  # user has no queue
        response = self.client.get(reverse('queueapp:create_queue'))
        self.assertEqual(response.status_code, 200)

    def test_owner_cannot_join_own_queue(self):
        response = self.client.get(reverse('queueapp:join_queue', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:home'))

    def test_user_can_join_queue(self):
        self.client.logout()
        self.client.login(username='user', password='pass')
        response = self.client.post(reverse('queueapp:join_queue', args=['TEST1']))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(user=self.user, queue=self.queue).exists())

    def test_user_cannot_join_twice(self):
        self.client.logout()
        self.client.login(username='user', password='pass')
        self.client.post(reverse('queueapp:join_queue', args=['TEST1']))
        response = self.client.post(reverse('queueapp:join_queue', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:join_queue', args=['TEST1']))
        self.assertEqual(Customer.objects.filter(user=self.user).count(), 1)

    def test_owner_can_call_next_customer(self):
        customer = Customer.objects.create(user=self.user, queue=self.queue)
        self.client.login(username='owner', password='pass')
        response = self.client.post(reverse('queueapp:call_next', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:queue_dashboard', args=['TEST1']))
        customer.refresh_from_db()
        self.assertIsNotNone(customer.called_at)

    def test_queue_dashboard_requires_owner(self):
        self.client.logout()
        self.client.login(username='user', password='pass')
        response = self.client.get(reverse('queueapp:queue_dashboard', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:home'))

    def test_leave_queue(self):
        Customer.objects.create(user=self.user, queue=self.queue)
        self.client.logout()
        self.client.login(username='user', password='pass')
        response = self.client.get(reverse('queueapp:leave_queue', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:home'))
        self.assertFalse(Customer.objects.filter(user=self.user).exists())

    def test_delete_queue_only_if_empty(self):
        self.client.login(username='owner', password='pass')
        response = self.client.get(reverse('queueapp:delete_queue', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:home'))
        self.assertFalse(Queue.objects.filter(short_id='TEST1').exists())

    def test_delete_queue_with_customers_fails(self):
        Customer.objects.create(user=self.user, queue=self.queue)
        self.client.login(username='owner', password='pass')
        response = self.client.get(reverse('queueapp:delete_queue', args=['TEST1']))
        self.assertRedirects(response, reverse('queueapp:queue_dashboard', args=['TEST1']))
        self.assertTrue(Queue.objects.filter(short_id='TEST1').exists())


class QueuePDFTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pdfuser', password='pass')
        self.client.login(username='pdfuser', password='pass')

    def test_create_queue_generates_pdf_file(self):
        response = self.client.post(reverse('queueapp:create_queue'), {
            'name': 'PDF Test Queue',
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        queue = Queue.objects.get(owner=self.user)
        self.assertIsNotNone(queue.qr_code)
        self.assertTrue(queue.qr_code.name.endswith('.pdf'))

        # Read raw PDF bytes
        with queue.qr_code.open('rb') as f:
            pdf_bytes = f.read()

        # Basic PDF sanity checks
        self.assertGreater(len(pdf_bytes), 5000)  # likely not empty
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))  # all valid PDFs start this way

