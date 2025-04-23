from gevent import server

class StreamServer(server.StreamServer):
    def handle_error(self, client_socket, address, exception):
        
