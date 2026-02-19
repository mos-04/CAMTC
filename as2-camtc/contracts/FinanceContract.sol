// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract FinanceContract {
    enum OrderType { MARKET, LIMIT, STOP, HFT }
    enum OrderStatus { PENDING, EXECUTED, SETTLED, CANCELLED }

    struct Order {
        bytes32 orderId;
        OrderType orderType;
        uint256 amount;
        uint256 price;
        uint8 priorityTier;
        uint256 timestamp;
        address trader;
        OrderStatus status;
        uint256 executionTime;
        bytes32 blockchainBlockHash;
    }

    mapping(bytes32 => Order) public orders;
    mapping(address => bool) public authorizedTraders;

    uint256 public nextOrderIndex;
    uint256 public totalOrders;
    uint256 public hftCount;
    uint256 public settledCount;

    event OrderPlaced(uint256 indexed orderIndex, bytes32 orderId, address trader, OrderType orderType, uint8 priorityTier, uint256 timestamp);
    event OrderExecuted(uint256 indexed orderIndex, bytes32 orderId, uint256 executionTime);
    event OrderSettled(uint256 indexed orderIndex, bytes32 orderId, uint256 settlementTime);

    modifier onlyAuthorized() {
        require(authorizedTraders[msg.sender], "Not authorized");
        _;
    }

    constructor() {
        authorizedTraders[msg.sender] = true;
    }

    function authorize(address trader) external {
        require(authorizedTraders[msg.sender] || msg.sender == address(this), "Only existing auth");
        authorizedTraders[trader] = true;
    }

    function placeOrder(
        bytes32 orderId,
        OrderType orderType,
        uint256 amount,
        uint256 price,
        uint8 priorityTier,
        bytes32 blockHash
    ) external onlyAuthorized returns (uint256) {
        uint256 idx = nextOrderIndex++;
        orders[orderId] = Order({
            orderId: orderId,
            orderType: orderType,
            amount: amount,
            price: price,
            priorityTier: priorityTier,
            timestamp: block.timestamp,
            trader: msg.sender,
            status: OrderStatus.PENDING,
            executionTime: 0,
            blockchainBlockHash: blockHash
        });
        totalOrders++;
        if (orderType == OrderType.HFT) hftCount++;
        emit OrderPlaced(idx, orderId, msg.sender, orderType, priorityTier, block.timestamp);
        return idx;
    }

    function executeOrder(bytes32 orderId) external onlyAuthorized {
        Order storage o = orders[orderId];
        require(o.timestamp != 0, "Order not found");
        require(o.status == OrderStatus.PENDING, "Not pending");
        o.status = OrderStatus.EXECUTED;
        o.executionTime = block.timestamp;
        emit OrderExecuted(nextOrderIndex - 1, orderId, block.timestamp);
    }

    function settleOrder(bytes32 orderId) external onlyAuthorized {
        Order storage o = orders[orderId];
        require(o.timestamp != 0, "Order not found");
        require(o.status == OrderStatus.EXECUTED, "Not executed");
        o.status = OrderStatus.SETTLED;
        settledCount++;
        emit OrderSettled(nextOrderIndex - 1, orderId, block.timestamp);
    }

    function getStats() external view returns (uint256 total, uint256 hft, uint256 settled) {
        total = totalOrders;
        hft = hftCount;
        settled = settledCount;
    }
}
