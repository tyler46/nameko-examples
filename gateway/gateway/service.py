import json

from marshmallow import ValidationError
from nameko.exceptions import BadRequest
from nameko.rpc import RpcProxy
from werkzeug import Response

from gateway.dependencies import Config
from gateway.entrypoints import http
from gateway.exceptions import OrderNotFound, ProductNotFound
from gateway.schemas import CreateOrderSchema


class Gateway(object):
    """
    Service acts as a gateway to other services over http.
    """

    name = 'gateway'

    config = Config()
    orders_rpc = RpcProxy('orders')
    products_rpc = RpcProxy('products')

    @http("GET", "/orders/<int:order_id>", expected_exceptions=OrderNotFound)
    def get_order(self, request, order_id):
        """Gets the order details for the order given by `order_id`.

        Enhances the order details with full product details from the
        products-service.
        """
        order = self._get_order(order_id)
        return Response(json.dumps(order), mimetype='application/json')

    def _get_order(self, order_id):
        # Retrieve order data from the orders service.
        # Note - this may raise a remote exception that has been mapped to
        # raise``OrderNotFound``
        order = self.orders_rpc.get_order(order_id)

        # Retrieve all products from the products service
        product_map = {prod['id']: prod for prod in self.products_rpc.list()}

        # get the configured image root
        image_root = self.config['PRODUCT_IMAGE_ROOT']

        # Enhance order details with product and image details.
        for item in order['order_details']:
            product_id = item['product_id']

            item['product'] = product_map[product_id]
            # Construct an image url.
            item['image'] = '{}/{}.jpg'.format(image_root, product_id)

        return order

    @http(
        "POST", "/orders",
        expected_exceptions=(ValidationError, ProductNotFound, BadRequest)
    )
    def create_order(self, request):
        """Create a new order - order data is posted as json
        """
        try:
            raw_data = json.loads(request.get_data(as_text=True))
        except ValueError as exc:
            raise BadRequest("Invalid json: {}".format(exc))

        # load input data through a schema (for validation)
        # Note - this may raise `ValidationError`
        schema = CreateOrderSchema(strict=True)
        order_data = schema.load(raw_data).data

        # Create the order
        # Note - this may raise `ProductNotFound`
        id_ = self._create_order(order_data)
        return Response(json.dumps({'id': id_}), mimetype='application/json')

    def _create_order(self, order_data):
        # check order product ids are valid
        # TODO - should the orders service do this validation instead?
        valid_product_ids = {prod['id'] for prod in self.products_rpc.list()}
        for item in order_data['order_details']:
            if item['product_id'] not in valid_product_ids:
                raise ProductNotFound(
                    "Product Id {}".format(item['product_id'])
                )

        # Call orders-service to create the order.
        # Dump the data through the schema to ensure the values are serialized
        # correctly.
        serialized_data = CreateOrderSchema().dump(order_data).data
        result = self.orders_rpc.create_order(
            serialized_data['order_details']
        )
        return result['id']
