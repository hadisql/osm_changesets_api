from rest_framework.pagination import PageNumberPagination


class ChangesetPagination(PageNumberPagination):
    """Default pagination, with a client-adjustable page size (used by the live map)."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500
