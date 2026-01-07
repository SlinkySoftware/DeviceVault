# Group Management - Quick Start Guide

## ✅ Feature Status: Ready to Use

The Group Management feature is fully implemented and ready for production use.

## 🚀 Quick Access

### As an Administrator

1. **Navigate to Groups**
   - Log in to DeviceVault
   - Click "Admin Settings" in the left sidebar
   - Click "Groups"

2. **Create Your First Group**
   - Click the "Add Group" button
   - Enter a name: "My Team"
   - Add a description (optional)
   - Select labels (tags) the group should have
   - Select users who should be in the group
   - Click "Save"

3. **View Groups**
   - See all groups in a table
   - View member count and assigned labels for each group
   - Groups are ordered alphabetically by name

## 🎯 What This Feature Does

### For Administrators
- Create and manage user groups
- Assign labels/tags to entire groups at once
- Add/remove users from groups
- Quickly see how many members each group has
- See all labels assigned to a group

### For Users
- Users inherit all labels assigned to their groups
- One group membership = access to multiple labels
- Simplifies permission management

## 📊 Example Use Cases

### Example 1: Department-Based Groups
```
Group: "Network Operations"
├─ Labels: ["Network", "Critical", "Production"]
└─ Members: Alice (ops), Bob (engineer), Charlie (manager)
```
All three users automatically get Network + Critical + Production access.

### Example 2: Project-Based Groups
```
Group: "Website Redesign Project"
├─ Labels: ["Development", "Testing"]
└─ Members: Dev Team, QA Team
```
All project members get Development and Testing access.

### Example 3: Shift-Based Groups
```
Group: "Night Shift"
├─ Labels: ["After-Hours", "Emergency"]
└─ Members: 5 on-call staff
```
Night shift staff have after-hours and emergency access.

## 🎮 Basic Operations

### Creating a Group
1. Click "Add Group" → Fill form → Save
2. Takes ~5 seconds

### Editing a Group
1. Click edit icon (pencil) → Modify fields → Save
2. Changes apply immediately

### Deleting a Group
1. Click delete icon (trash) → Confirm → Group removed
2. Undo not available - confirm carefully

### Adding Users to a Group
1. Click edit → Select more users → Save
2. New members inherit group's labels immediately

### Changing Group Labels
1. Click edit → Modify labels → Save
2. All members' access updated automatically

## 💾 Data Storage

- Groups stored in database table: `rbac_group`
- Group members stored in: `rbac_group_users` junction table
- Group labels stored in: `rbac_group_labels` junction table
- All changes are persistent

## 🔍 Viewing Details

### In Group Table
| Column | Shows |
|--------|-------|
| Name | Group name |
| Description | Group purpose |
| Members | How many users in group |
| Labels | Tags assigned to group |
| Actions | Edit/Delete buttons |

### In Edit Dialog
- All group information
- Current members list
- Current labels list
- Option to add/remove both

## ⚡ Performance Tips

1. **Large Groups**: Works smoothly with 100+ members
2. **Bulk Operations**: Edit multiple users into group at once
3. **Search**: Use browser find (Ctrl+F) to find groups in table
4. **Labels**: Assign multiple labels at once instead of one by one

## ❓ FAQ

**Q: Can a user be in multiple groups?**
A: Yes! One user can be in many groups. They'll inherit all labels from all their groups.

**Q: What happens if I delete a group?**
A: Users in that group lose those labels, but the users aren't deleted.

**Q: Can I rename a group?**
A: Yes! Click edit and change the name.

**Q: Do group changes apply immediately?**
A: Yes! All changes are instant - no restart needed.

**Q: Can I duplicate a group?**
A: Not built-in, but you can create a similar group manually with same labels/users.

## 🐛 Troubleshooting

### Groups Page Doesn't Load
- Verify you're logged in
- Verify you're an admin
- Check browser console for errors

### Can't Add Users to Group
- Make sure user exists in system
- User might already be in group
- Check for network errors

### Changes Not Saving
- Check for validation errors (red text)
- Name might already be used by another group
- Required fields might be empty

### Users Not Appearing in Dropdown
- Refresh the page
- Check if users exist in system
- Check network connection

## 📞 Support

For issues or feature requests:
1. Check this guide
2. Review GROUP_MANAGEMENT_FEATURE.md for technical details
3. Check browser console for error messages
4. Review Django logs: `backend/logs/` directory

## 🎓 Next Steps

1. ✅ Create first group
2. ✅ Add team members to group
3. ✅ Assign labels to group
4. ✅ Verify users can access associated devices
5. ✅ Set up additional groups as needed

## 📈 Best Practices

1. **Naming**: Use clear, descriptive group names
   - ✅ Good: "Production Support Team"
   - ❌ Bad: "Group1"

2. **Descriptions**: Always add descriptions
   - Helps others understand group purpose
   - Makes it easy to find the right group

3. **Labels**: Assign labels carefully
   - Don't overload with too many labels
   - Keep labels consistent across groups

4. **Membership**: Keep groups up to date
   - Remove users who leave team
   - Add new team members promptly

5. **Auditing**: Periodically review groups
   - Check for unused groups
   - Update stale descriptions

---

**You're all set!** The Group Management feature is ready to use. Start creating groups to streamline your access management.
