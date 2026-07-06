#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/beast/ssl.hpp>
#include <iostream>
#include <string>
#include <memory>
#include <chrono>
#include "json.hpp"

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
using json = nlohmann::json;

class ProxyServer : public std::enable_shared_from_this<ProxyServer> {
    asio::ip::tcp::acceptor acceptor_;

public:
    ProxyServer(asio::io_context& ioc, const std::string& host, short port)
        : acceptor_(ioc, {asio::ip::make_address(host), (unsigned short)port}) {}

    void run() { accept(); }

private:
    void accept() {
        acceptor_.async_accept([this](boost::system::error_code ec, asio::ip::tcp::socket socket) {
            if (!ec) {
                std::make_shared<Session>(std::move(socket))->start();
            }
            accept();
        });
    }

    class Session : public std::enable_shared_from_this<Session> {
        beast::tcp_stream stream_;
        beast::flat_buffer buffer_;
        http::request<http::string_body> req_;

    public:
        Session(asio::ip::tcp::socket socket) : stream_(std::move(socket)) {}

        void start() { read(); }

    private:
        void read() {
            req_ = {};
            http::async_read(stream_, buffer_, req_, [self = shared_from_this()](beast::error_code ec, std::size_t) {
                if (!ec) self->handle();
            });
        }

        void handle() {
            if (req_.target() == "/v1/messages") {
                // Forward to NVIDIA (simulated simplified logic)
                auto body = json::parse(req_.body());
                std::cout << "C++ Proxy: Forwarding " << body["model"] << std::endl;

                http::response<http::string_body> res{http::status::ok, req_.version()};
                res.set(http::field::content_type, "application/json");
                res.body() = R"({"id":"msg_cpp","type":"message","role":"assistant","content":[{"type":"text","text":"Hello from C++!"}],"usage":{"input_tokens":1,"output_tokens":1}})";
                res.prepare_payload();
                http::write(stream_, res);
            } else if (req_.target() == "/admin") {
                http::response<http::string_body> res{http::status::ok, req_.version()};
                res.body() = "<h1>C++ Proxy Admin</h1>";
                res.prepare_payload();
                http::write(stream_, res);
            } else {
                http::response<http::string_body> res{http::status::not_found, req_.version()};
                res.prepare_payload();
                http::write(stream_, res);
            }
        }
    };
};

int main() {
    try {
        asio::io_context ioc;
        auto server = std::make_shared<ProxyServer>(ioc, "127.0.0.1", 2424);
        std::cout << "🚀 C++ High-Performance Proxy running on http://127.0.0.1:2424" << std::endl;
        server->run();
        ioc.run();
    } catch (std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
    }
    return 0;
}
