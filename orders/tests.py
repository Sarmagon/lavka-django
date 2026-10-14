from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import Client, TestCase, override_settings
from django.utils import timezone
from accounts.models import User
from catalog.models import Category, Product, Seller, Offer, Discount
from .models import Order, OrderItem, DeliverySettings, PaymentJob
from .services import delivery_cost
from .payment_worker import process_one
from .mock_payment import simulate


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CheckoutPaymentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="checkout", email="checkout@example.com", full_name="Покупатель", phone="+79991234567", password="Some-pass-908!")
        cls.other = User.objects.create_user(username="another", email="another@example.com", full_name="Другой покупатель", password="Some-pass-908!")
        category = Category.objects.create(name="Техника")
        cls.product = Product.objects.create(title="Товар", category=category, manufacturer="Бренд")
        cls.offer = Offer.objects.create(product=cls.product, seller=Seller.objects.create(name="Продавец"), price=1000, stock=10)
        cls.cfg = DeliverySettings.objects.order_by('pk').first() or DeliverySettings.objects.create()

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['basket'] = {str(self.product.pk): 2}
        session.save()

    def test_login_by_email_after_checkout_registration(self):
        self.client.logout()
        response = self.client.post('/api/sign-in', {'username':self.user.email.upper(), 'password':'Some-pass-908!'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/account').json()['fullName'], self.user.full_name)

    def data(self, **changes):
        key = self.client.get('/api/checkout').json()['checkoutKey']
        return dict(checkoutKey=key, fullName='Покупатель', email=self.user.email, phone=self.user.phone,
            city='Москва', address='Тестовая, 1', deliveryType='ordinary', paymentType='online', comment='Позвонить', **changes)

    def post(self, path, data):
        return self.client.post(path, data, content_type='application/json')

    def order(self):
        response = self.post('/api/orders', self.data())
        self.assertEqual(response.status_code, 201, response.content)
        return Order.objects.get(pk=response.json()['orderId'])

    def test_delivery_boundaries_and_admin_settings(self):
        self.assertEqual(delivery_cost(Decimal('1999.99'),'ordinary'), 200)
        self.assertEqual(delivery_cost(Decimal('2000'),'ordinary'), 0)
        self.assertEqual(delivery_cost(Decimal('2000.01'),'express'), 500)
        self.assertEqual(delivery_cost(Decimal('1999'),'express'), 700)
        self.cfg.free_from, self.cfg.ordinary_cost, self.cfg.express_extra = 3000, 150, 650
        self.cfg.save()
        self.assertEqual(delivery_cost(Decimal('2000'),'express'), 800)

    def test_snapshot_and_duplicate_confirmation(self):
        data = self.data()
        first = self.post('/api/orders', {**data, 'totalCost': 1, 'products': [], 'userId': self.other.pk})
        self.assertEqual(first.status_code, 201)
        repeated = self.post('/api/orders', data)
        self.assertEqual(repeated.json()['orderId'], first.json()['orderId'])
        self.assertEqual(Order.objects.filter(user=self.user).count(),1)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.stock,8)
        self.assertEqual(self.client.session['basket'],{})
        self.offer.price=9000; self.offer.save()
        self.product.title='Другое название'; self.product.save()
        saved = self.client.get('/api/order/'+str(first.json()['orderId'])).json()
        self.assertEqual(saved['totalCost'],2000)
        self.assertEqual(saved['products'][0]['title'],'Товар')

    def test_discount_snapshot(self):
        now=timezone.now()
        Discount.objects.create(product=self.product,percent=10,starts_at=now-timedelta(days=1),ends_at=now+timedelta(days=1))
        order=self.order()
        self.assertEqual(order.items.first().unit_price,Decimal('900'))
        self.assertEqual(order.delivery_cost,200)

    def test_missing_stock_and_invalid_fields_leave_database_unchanged(self):
        data=self.data()
        self.offer.stock=1;self.offer.save()
        response=self.post('/api/orders',data)
        self.assertEqual(response.status_code,409)
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.offer.refresh_from_db();self.assertEqual(self.offer.stock,1)
        for field,value in [('email','bad'),('phone','abc'),('city',''),('address',''),('paymentType','cash'),('comment','x'*2001)]:
            response=self.post('/api/orders',{**data,field:value})
            self.assertEqual(response.status_code,400)
            self.assertIn(field,response.json()['errors'])

    def test_ownership_authentication_and_soft_delete(self):
        order=self.order()
        self.client.force_login(self.other)
        for path in [f'/api/order/{order.pk}',f'/api/payment/{order.pk}',f'/order-detail/{order.pk}/',f'/payment/{order.pk}/']:
            self.assertEqual(self.client.get(path).status_code,404,path)
        self.assertEqual(self.client.get('/api/orders').json(),[])
        self.client.logout()
        self.assertEqual(self.client.get('/api/orders').status_code,401)
        self.assertEqual(self.client.get('/history-order/').status_code,302)
        self.client.force_login(self.user)
        order.delete()
        self.assertEqual(self.client.get(f'/api/order/{order.pk}').status_code,404)

    def test_guest_registration_and_duplicate_email_message(self):
        self.client.logout()
        session=self.client.session;session['basket']={str(self.product.pk):2};session.save()
        self.assertEqual(self.post('/api/orders',self.data()).status_code,401)
        data={'fullName':'Гость','email':'guest@example.com','phone':'+79991234568','password':'Guest-password-784!','passwordReply':'Guest-password-784!'}
        bad=self.post('/api/checkout/register',{**data,'passwordReply':'different'})
        self.assertEqual(bad.status_code,400)
        response=self.post('/api/checkout/register',data)
        self.assertEqual(response.status_code,201,response.content)
        self.assertTrue(self.client.session['_auth_user_id'])
        self.assertEqual(self.client.session['basket'][str(self.product.pk)],2)
        self.client.logout()
        duplicate=self.post('/api/checkout/register',data)
        self.assertEqual(duplicate.json()['errors']['email'],'Пользователь с указанным email существует, вы можете авторизоваться')

    def test_payment_queue_success_duplicate_and_no_second_stock_decrement(self):
        order=self.order()
        path=f'/api/payment/{order.pk}'
        first=self.post(path,{'number':'12345678'})
        repeated=self.post(path,{'number':'12345678'})
        self.assertEqual(first.status_code,202)
        self.assertEqual(first.json()['jobId'],repeated.json()['jobId'])
        self.assertEqual(PaymentJob.objects.count(),1)
        process_one(lambda job:simulate(job.number))
        order.refresh_from_db();self.assertEqual(order.status,'paid')
        self.offer.refresh_from_db();self.assertEqual(self.offer.stock,8)
        self.assertFalse(process_one())
        self.assertEqual(self.post(path,{'number':'12345678'}).status_code,409)

    def test_payment_validation_and_error_retry_with_other_method(self):
        order=self.order();path=f'/api/payment/{order.pk}'
        for number in ['123','123456789','text','',12,None,True]:
            self.assertEqual(self.post(path,{'number':number}).status_code,400)
        self.post(path,{'number':'12345670'})
        process_one(lambda job:simulate(job.number))
        order.refresh_from_db();self.assertEqual(order.status,'failed');self.assertTrue(order.payment_error)
        self.assertEqual(self.post(path,{'number':'00000002','paymentType':'someone'}).status_code,202)
        process_one(lambda job:simulate(job.number))
        order.refresh_from_db();self.assertEqual(order.status,'paid');self.assertEqual(order.payment_type,'someone')
        self.assertEqual(order.payment_error,'')
        self.offer.refresh_from_db();self.assertEqual(self.offer.stock,8)

    def test_mock_service_rejects_bypassed_numbers(self):
        for value in ['123','1000','00000000','123456789','abc',True]:
            self.assertFalse(simulate(value)['success'])
        self.assertTrue(simulate('12345678')['success'])

    def test_worker_transport_failure_retry_and_final_error(self):
        order=self.order();self.post(f'/api/payment/{order.pk}',{'number':'12345678'})
        def broken(job): raise OSError('offline')
        for attempt in range(3):
            PaymentJob.objects.update(lease_until=timezone.now()-timedelta(seconds=1))
            process_one(broken)
        order.refresh_from_db();self.assertEqual(order.status,'failed')
        self.assertIn('недоступен',order.payment_error)
        self.assertEqual(PaymentJob.objects.get().state,'done')

    def test_worker_recovers_expired_lease_and_skips_live_lease(self):
        order=self.order();self.post(f'/api/payment/{order.pk}',{'number':'12345678'})
        PaymentJob.objects.update(state='running',lease_token=uuid4(),lease_until=timezone.now()+timedelta(minutes=1))
        self.assertFalse(process_one(lambda job:simulate(job.number)))
        PaymentJob.objects.update(lease_until=timezone.now()-timedelta(seconds=1))
        self.assertTrue(process_one(lambda job:simulate(job.number)))
        order.refresh_from_db();self.assertEqual(order.status,'paid')

    def test_account_history_and_template_routes(self):
        order=self.order()
        self.assertEqual(self.client.get('/api/account').json()['orders'][0]['id'],order.pk)
        self.assertEqual(self.client.get('/api/orders').json()[0]['id'],order.pk)
        for path in ['/checkout/','/account/','/history-order/',f'/order-detail/{order.pk}/',f'/payment/{order.pk}/',f'/payment-someone/?order={order.pk}',f'/progress-payment/?order={order.pk}','/profile/','/cart/']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
        self.assertContains(self.client.get('/checkout/'),'Комментарий к заказу')
        self.assertContains(self.client.get('/checkout/'),'Я уже зарегистрирован')
        self.assertContains(self.client.get('/profile/'),'История заказов')

    def test_csrf_not_disabled(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/api/orders',{},content_type='application/json').status_code,403)
