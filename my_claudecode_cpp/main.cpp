#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <iostream>
#include <string>
#include <thread>

namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = boost::asio::ip::tcp;

extern void handle_request(http::request<http::string_body>&& req, http::response<http::string_body>& res);

void do_session(tcp::socket socket) {
    try {
        beast::flat_buffer buffer;
        http::request<http::string_body> req;
        http::read(socket, buffer, req);
        http::response<http::string_body> res;
        handle_request(std::move(req), res);
        http::write(socket, res);
    } catch(std::exception const& e) {
        std::cerr << "Error: " << e.what() << std::endl;
    }
}

int main() {
    try {
        auto const address = net::ip::make_address("127.0.0.1");
        unsigned short port = 2424;
        net::io_context ioc{1};
        tcp::acceptor acceptor{ioc, {address, port}};
        std::cout << "🚀 C++ Proxy Server: http://127.0.0.1:2424" << std::endl;
        for(;;) {
            tcp::socket socket{ioc};
            acceptor.accept(socket);
            std::thread{do_session, std::move(socket)}.detach();
        }
    } catch (std::exception const& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return EXIT_FAILURE;
    }
}
