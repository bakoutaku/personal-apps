import Foundation

struct ActivityRecord: Identifiable {
    let id: UUID
    let event: CompanionEvent
    var isRead = false
}

/// Session-local history, intentionally kept in memory rather than writing conversation titles to disk.
struct EventHistory {
    private(set) var records: [ActivityRecord] = []
    var unreadCount: Int { records.filter { !$0.isRead }.count }
    mutating func insert(_ event: CompanionEvent) -> UUID {
        let record = ActivityRecord(id: UUID(), event: event)
        records.insert(record, at: 0)
        records = Array(records.prefix(20))
        return record.id
    }
    mutating func markRead(_ id: UUID) {
        guard let index = records.firstIndex(where: { $0.id == id }) else { return }
        records[index].isRead = true
    }
    mutating func markAllRead() { for i in records.indices { records[i].isRead = true } }
    mutating func clear() { records.removeAll() }
}
